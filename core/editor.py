"""Chỉnh sửa video trước khi đăng: phiên âm (whisper.cpp) -> sửa phụ đề -> xuất bản 9:16 bằng FFmpeg.

Mỗi thư mục video có thể có thêm:
  subs.json          phụ đề: {"language", "model", "cues": [{"start", "end", "text"}]} (giây)
  voice.<đuôi>       giọng đọc / bình luận của bạn (tùy chọn), được trộn vào âm thanh
  edit.json          cài đặt lần xuất gần nhất
  video.draft.mp4    bản nháp do "Xuất video" tạo; video.mp4 vẫn nguyên cho tới khi bạn bấm Duyệt
  edit_approved.json dấu "đã duyệt"; sau khi Duyệt, bản nháp THAY THẾ video.mp4 (video gốc bị xoá, không khôi phục được)

Công cụ ngoài: ffmpeg (có bộ lọc subtitles/libass) và whisper-cli (whisper.cpp) cùng một file model ggml.
Đường dẫn tự tìm; đặt FFMPEG_PATH, WHISPER_CLI, WHISPER_MODEL (đường dẫn hoặc tên như large-v3-turbo) trong .env nếu ở chỗ khác.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from . import config, library, reelcheck
from .videofile import APPROVED, DRAFT, ORIGINAL

SUBS_FILE = "subs.json"
SETTINGS_FILE = "edit.json"
VOICE_STEM = "voice"
VOICE_EXTS = (".mp3", ".m4a", ".wav", ".aac", ".ogg", ".flac", ".opus")
MAX_VOICE_BYTES = 300 * 1024 * 1024
MAX_CUES = 3000
MAX_CUE_CHARS = 200
OUT_W, OUT_H = 1080, 1920
LANGS = {"vi": "Tiếng Việt", "en": "English", "ja": "日本語", "zh": "中文", "ko": "한국어", "th": "ไทย", "auto": "Tự nhận diện"}

DEFAULT_SETTINGS = {
    "framing": "auto",       # auto | scale | fit | crop
    "subs": True,            # in phụ đề vào video
    "position": "bottom",    # bottom | middle | top
    "size": "medium",        # small | medium | large
    "color": "white",        # white | yellow | cyan
    "box": False,            # nền mờ phía sau chữ
    "orig_volume": 25,       # % âm lượng video gốc khi có giọng đọc
    "voice_volume": 100,     # % âm lượng giọng đọc
    "loudnorm": True,        # chuẩn hóa âm lượng về mức Reels hay dùng
}
CHOICES = {"framing": ("auto", "scale", "fit", "crop"), "position": ("bottom", "middle", "top"),
           "size": ("small", "medium", "large"), "color": ("white", "yellow", "cyan")}
FONT_SIZES = {"small": 54, "medium": 66, "large": 80}
COLORS = {"white": "&H00FFFFFF", "yellow": "&H0000E6FF", "cyan": "&H00FFE600"}   # ASS dùng thứ tự BGR
ALIGN = {"bottom": (2, 330), "middle": (5, 0), "top": (8, 260)}                    # (Alignment, MarginV)

_busy = threading.Lock()


class EditError(Exception):
    """Lỗi hiện cho người dùng."""


# ---------- tìm công cụ ----------
_EXTRA_PATH = os.pathsep.join(["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"])


def _run(cmd: list[str], timeout: float = 20) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, errors="replace")


def _ffmpeg_candidates() -> list[str]:
    out = []
    for c in (os.environ.get("FFMPEG_PATH", ""), "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg", shutil.which("ffmpeg") or "",
              shutil.which("ffmpeg", path=_EXTRA_PATH) or ""):
        if c and c not in out and Path(c).exists():
            out.append(c)
    return out


def _has_filter(exe: str, name: str) -> bool:
    try:
        r = _run([exe, "-hide_banner", "-filters"])
    except (OSError, subprocess.SubprocessError):
        return False
    return re.search(rf"\s{re.escape(name)}\s", r.stdout) is not None


_tools_cache: dict = {"at": 0.0, "val": None}


def tools(refresh: bool = False) -> dict:
    """{"ffmpeg": {path, ok, libass, problem}, "ffprobe": path, "whisper": {cli, model, ok, problem}}. Có nhớ tạm 30 giây."""
    now = time.time()
    if not refresh and _tools_cache["val"] is not None and now - _tools_cache["at"] < 30:
        return _tools_cache["val"]
    ff = {"path": "", "ok": False, "libass": False, "problem": ""}
    for c in _ffmpeg_candidates():   # ưu tiên bản có phụ đề; nếu không bản nào có thì giữ bản đầu tiên để báo đúng nguyên nhân
        sub = _has_filter(c, "subtitles")
        if not ff["path"] or sub:
            ff.update(path=c, ok=True, libass=sub)
        if sub:
            break
    if not ff["path"]:
        ff["problem"] = "Chưa cài FFmpeg. Chạy: bash tools/install_editor_tools.sh"
    elif not ff["libass"]:
        ff["problem"] = "FFmpeg này thiếu bộ lọc subtitles (libass), chưa in được phụ đề. Cài bản đầy đủ: brew uninstall ffmpeg && brew install ffmpeg-full"
    probe = ""
    if ff["path"]:
        sib = Path(ff["path"]).with_name("ffprobe")
        probe = str(sib) if sib.exists() else (reelcheck.ffprobe_path() or "")
    wh = {"cli": "", "model": "", "ok": False, "problem": ""}
    home = Path(os.environ.get("WHISPER_DIR") or Path.home() / "tools" / "whisper.cpp").expanduser()
    for c in (os.environ.get("WHISPER_CLI", ""), str(home / "build" / "bin" / "whisper-cli"), shutil.which("whisper-cli") or "",
              shutil.which("whisper-cli", path=_EXTRA_PATH) or ""):
        if c and Path(c).exists():
            wh["cli"] = c
            break
    wh["model"] = _find_model(home)
    if not wh["cli"]:
        wh["problem"] = "Chưa có whisper-cli (whisper.cpp). Chạy: bash tools/install_editor_tools.sh"
    elif not wh["model"]:
        wh["problem"] = "Chưa có model whisper (file ggml-*.bin). Chạy: bash tools/install_editor_tools.sh"
    else:
        wh["ok"] = True
    val = {"ffmpeg": ff, "ffprobe": probe, "whisper": wh}
    _tools_cache.update(at=now, val=val)
    return val


MODEL_PREFERENCE = ("large-v3-turbo", "large-v3", "medium", "small", "base", "tiny")


def _find_model(home: Path) -> str:
    want = os.environ.get("WHISPER_MODEL", "").strip()
    if want:
        p = Path(want).expanduser()
        if p.is_file():
            return str(p)
        q = home / "models" / f"ggml-{want}.bin"
        if q.is_file():
            return str(q)
        return ""
    for name in MODEL_PREFERENCE:
        q = home / "models" / f"ggml-{name}.bin"
        if q.is_file():
            return str(q)
    return ""


# ---------- đọc/ghi dữ liệu của một video ----------
def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def voice_file(folder: Path) -> Path | None:
    for ext in VOICE_EXTS:
        p = folder / f"{VOICE_STEM}{ext}"
        if p.is_file():
            return p
    return None


def probe_media(path: Path) -> dict:
    """{"width", "height", "duration", "has_audio"} (0/False nếu không đọc được)."""
    out = {"width": 0, "height": 0, "duration": 0.0, "has_audio": False}
    exe = tools()["ffprobe"]
    if not exe or not path.exists():
        return out
    try:
        r = _run([exe, "-v", "error", "-show_entries", "stream=codec_type,width,height,duration:format=duration", "-of", "json", str(path)], 30)
        data = json.loads(r.stdout or "{}")
    except (OSError, subprocess.SubprocessError, ValueError):
        return out
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and not out["width"]:
            out["width"], out["height"] = int(s.get("width") or 0), int(s.get("height") or 0)
        elif s.get("codec_type") == "audio":
            out["has_audio"] = True
    try:
        out["duration"] = float((data.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        pass
    return out


def clean_settings(raw: dict | None) -> dict:
    s = dict(DEFAULT_SETTINGS)
    raw = raw if isinstance(raw, dict) else {}
    for k, allowed in CHOICES.items():
        if raw.get(k) in allowed:
            s[k] = raw[k]
    for k in ("subs", "box", "loudnorm"):
        if isinstance(raw.get(k), bool):
            s[k] = raw[k]
    for k, lo, hi in (("orig_volume", 0, 200), ("voice_volume", 0, 300)):
        try:
            s[k] = max(lo, min(hi, int(raw.get(k, s[k]))))
        except (TypeError, ValueError):
            pass
    return s


def clean_cues(cues, duration: float = 0.0) -> list[dict]:
    """Chuẩn hóa danh sách phụ đề: bỏ dòng rỗng/hỏng, sắp theo thời gian, không chồng lấn, nằm trong độ dài video."""
    if not isinstance(cues, list):
        raise EditError("Danh sách phụ đề không hợp lệ.")
    if len(cues) > MAX_CUES:
        raise EditError(f"Quá nhiều dòng phụ đề (tối đa {MAX_CUES}).")
    out = []
    for c in cues:
        if not isinstance(c, dict):
            continue
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(c.get("text", "")))
        text = "\n".join(line.strip() for line in text.replace("\r", "").split("\n") if line.strip())[:MAX_CUE_CHARS].strip()
        try:
            start, end = float(c.get("start")), float(c.get("end"))
        except (TypeError, ValueError):
            continue
        if not text or start != start or end != end or start < 0:
            continue
        if end <= start:
            end = start + 1.0
        if duration:
            if start >= duration:
                continue
            end = min(end, duration)
        out.append({"start": round(start, 2), "end": round(end, 2), "text": text})
    out.sort(key=lambda x: (x["start"], x["end"]))
    for a, b in zip(out, out[1:]):
        if a["end"] > b["start"]:
            a["end"] = max(round(a["start"] + 0.2, 2), round(b["start"], 2))
    return out


def load_subs(folder: Path) -> dict:
    data = _read_json(folder / SUBS_FILE)
    data["cues"] = data["cues"] if isinstance(data.get("cues"), list) else []
    return data


def save_subs(rel: str, cues) -> dict:
    folder = library.resolve(rel)
    dur = probe_media(folder / ORIGINAL)["duration"]
    clean = clean_cues(cues, dur)
    data = load_subs(folder)
    data.update(cues=clean, edited_at=datetime.now(timezone.utc).isoformat())
    _write_json(folder / SUBS_FILE, data)
    return {"cues": clean}


# ---------- giọng đọc ----------
def save_voice(rel: str, filename: str, stream, length: int | None) -> dict:
    folder = library.resolve(rel)
    ext = Path(filename or "").suffix.lower()
    if ext not in VOICE_EXTS:
        raise EditError("Chỉ nhận file âm thanh: " + ", ".join(VOICE_EXTS))
    if length is not None and length > MAX_VOICE_BYTES:
        raise EditError("File âm thanh quá lớn (tối đa 300 MB).")
    tmp = folder / f"{VOICE_STEM}.upload.tmp"
    size = 0
    try:
        with open(tmp, "wb") as f:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_VOICE_BYTES:
                    raise EditError("File âm thanh quá lớn (tối đa 300 MB).")
                f.write(chunk)
        if size == 0:
            raise EditError("File âm thanh rỗng.")
        exe = tools()["ffprobe"]
        if exe:
            r = _run([exe, "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(tmp)], 30)
            if "audio" not in r.stdout:
                raise EditError("File này không có âm thanh đọc được.")
        remove_voice(rel)
        tmp.replace(folder / f"{VOICE_STEM}{ext}")
    finally:
        tmp.unlink(missing_ok=True)
    return voice_info(folder)


def remove_voice(rel: str) -> None:
    folder = library.resolve(rel)
    for ext in VOICE_EXTS:
        (folder / f"{VOICE_STEM}{ext}").unlink(missing_ok=True)


def voice_info(folder: Path) -> dict:
    v = voice_file(folder)
    if v is None:
        return {"name": "", "size_mb": 0, "duration": 0.0}
    return {"name": v.name, "size_mb": round(v.stat().st_size / 1048576, 2), "duration": round(probe_media(v)["duration"], 1)}


# ---------- trạng thái ----------
def is_scheduled(folder: Path) -> bool:
    return (folder / "scheduled.json").exists()


def status(rel: str) -> dict:
    folder = library.resolve(rel)
    t = tools()
    src = dict(probe_media(folder / ORIGINAL))
    try:
        src["size"] = (folder / ORIGINAL).stat().st_size   # để trình duyệt không dùng bản video cũ trong bộ nhớ đệm
    except OSError:
        src["size"] = 0
    subs = load_subs(folder)
    draft = folder / DRAFT
    dr = {"exists": False}
    if draft.is_file() and draft.stat().st_size > 0:
        st = draft.stat()
        info = _read_json(folder / SETTINGS_FILE)
        dr = {"exists": True, "size_mb": round(st.st_size / 1048576, 1), "mtime": int(st.st_mtime), "settings": info.get("settings", {}),
              "stale": subs.get("edited_at", subs.get("created_at", "")) > info.get("edited_at", "") if subs.get("cues") else False}
    settings = clean_settings(_read_json(folder / SETTINGS_FILE).get("settings"))
    return {"rel": rel, "tools": t, "source": src, "cues": subs["cues"], "language": subs.get("language", ""),
            "transcribed": bool(subs.get("created_at")), "voice": voice_info(folder), "draft": dr,
            "approved": _read_json(folder / APPROVED).get("approved_at", ""), "settings": settings,
            "scheduled": is_scheduled(folder), "langs": LANGS, "busy": _busy.locked()}


def discard(rel: str) -> None:
    """Bỏ bản nháp. Video đang dùng (video.mp4) không đổi; phụ đề và giọng đọc được giữ để xuất lại."""
    folder = library.resolve(rel)
    if not _busy.acquire(blocking=False):
        raise EditError("Đang có tác vụ chỉnh sửa khác chạy, đợi xong rồi thử lại.")
    try:
        (folder / DRAFT).unlink(missing_ok=True)
    finally:
        _busy.release()


def approve(rel: str) -> str:
    """Duyệt bản nháp: nó THAY THẾ video.mp4 (video cũ bị xoá hẳn). Phụ đề, giọng đọc và cài đặt cũ không còn ý nghĩa với video mới nên bị dọn."""
    folder = library.resolve(rel)
    if is_scheduled(folder):
        raise EditError("Video này đã lên lịch. Huỷ lịch trước rồi mới duyệt được.")
    if not _busy.acquire(blocking=False):
        raise EditError("Đang có tác vụ chỉnh sửa khác chạy, đợi xong rồi thử lại.")
    try:
        draft = folder / DRAFT
        if not draft.is_file() or draft.stat().st_size == 0:
            raise EditError("Chưa có bản nháp để duyệt. Hãy xuất video trước.")
        info = probe_media(draft)
        if not info["width"] or not info["duration"]:
            raise EditError("Bản nháp không đọc được (file hỏng?). Hãy xuất lại.")
        settings = _read_json(folder / SETTINGS_FILE).get("settings", {})
        os.replace(draft, folder / ORIGINAL)   # nguyên tử: video.mp4 luôn là một file đầy đủ
        for name in (SUBS_FILE, SETTINGS_FILE):
            (folder / name).unlink(missing_ok=True)
        remove_voice(rel)
        _write_json(folder / APPROVED, {"approved_at": datetime.now(timezone.utc).isoformat(), "settings": settings})
        if reelcheck.available():
            try:
                reelcheck.ensure(folder, force=True)
            except Exception:   # noqa: BLE001  kiểm tra Reels chỉ là phụ
                pass
        return f"Đã duyệt: bản chỉnh sửa đã thay thế video gốc ({info['width']}x{info['height']}, {info['duration']:.0f} giây)."
    finally:
        _busy.release()


# ---------- phiên âm ----------
_PROGRESS_RE = re.compile(r"progress\s*=\s*(\d+)%")
_JUNK_RE = re.compile(r"^\s*[\[(*].*[\])*]\s*$|^[^\w]*$")   # [BLANK_AUDIO], (nhạc), *tiếng động*, chỉ có dấu/♪


def parse_whisper_json(data: dict) -> list[dict]:
    """Đọc file .json do `whisper-cli -oj` ghi ra thành danh sách {start, end, text}."""
    cues = []
    for seg in data.get("transcription", []) if isinstance(data, dict) else []:
        text = str(seg.get("text", "")).strip()
        if not text or _JUNK_RE.match(text):
            continue
        off = seg.get("offsets") or {}
        try:
            start, end = float(off["from"]) / 1000.0, float(off["to"]) / 1000.0
        except (KeyError, TypeError, ValueError):
            ts = seg.get("timestamps") or {}
            start, end = _hms(ts.get("from")), _hms(ts.get("to"))
        cues.append({"start": start, "end": end, "text": re.sub(r"\s+", " ", text)})
    return cues


def _hms(s) -> float:
    m = re.match(r"^(\d+):(\d+):(\d+)[,.](\d+)$", str(s or ""))
    return int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3]) + int(m[4].ljust(3, "0")[:3]) / 1000 if m else 0.0


def _stop(proc: subprocess.Popen) -> None:
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        proc.kill()


def _tail(path: Path, n: int = 600) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-n:].strip()
    except OSError:
        return ""


def transcribe_job(job, rel: str, lang: str = "vi", source: str = "auto") -> str:
    if not _busy.acquire(blocking=False):
        raise EditError("Đang có một tác vụ chỉnh sửa khác chạy. Đợi nó xong rồi thử lại.")
    try:
        t = tools(refresh=True)
        if not t["ffmpeg"]["ok"]:
            raise EditError(t["ffmpeg"]["problem"])
        if not t["whisper"]["ok"]:
            raise EditError(t["whisper"]["problem"])
        if lang not in LANGS:
            lang = "vi"
        folder = library.resolve(rel)
        voice = voice_file(folder)
        use_voice = voice is not None and source in ("auto", "voice")
        audio_src = voice if use_voice else folder / ORIGINAL
        if not use_voice and not probe_media(audio_src)["has_audio"] and t["ffprobe"]:
            raise EditError("Video này không có âm thanh để phiên âm.")
        with tempfile.TemporaryDirectory(prefix="mvt-whisper-") as tmp:
            tmpd = Path(tmp)
            job.log(f"Tách âm thanh từ {audio_src.name}...")
            wav = tmpd / "audio.wav"
            err = tmpd / "ffmpeg.err"
            with open(err, "w") as ef:
                r = subprocess.run([t["ffmpeg"]["path"], "-nostdin", "-v", "error", "-y", "-i", str(audio_src), "-vn", "-ac", "1", "-ar", "16000",
                                    "-c:a", "pcm_s16le", str(wav)], stderr=ef, timeout=600)
            if r.returncode != 0 or not wav.exists():
                raise EditError("Không tách được âm thanh: " + _tail(err))
            job.log(f"Phiên âm bằng whisper.cpp (model {Path(t['whisper']['model']).name}, ngôn ngữ {LANGS[lang]})...")
            cmd = [t["whisper"]["cli"], "-m", t["whisper"]["model"], "-f", str(wav), "-l", lang, "-oj", "-of", str(tmpd / "out"),
                   "-ml", "36", "-sow", "-np", "-pp"]
            env = dict(os.environ)
            lib_dir = Path(t["whisper"]["cli"]).resolve().parent.parent
            env["LD_LIBRARY_PATH"] = os.pathsep.join([str(lib_dir / "src"), str(lib_dir / "ggml" / "src"), env.get("LD_LIBRARY_PATH", "")])
            log = tmpd / "whisper.log"
            with open(log, "w") as lf:
                proc = subprocess.Popen(cmd, stdout=lf, stderr=lf, env=env)
                last = -1
                while proc.poll() is None:
                    if job.cancelled:
                        _stop(proc)
                        return "Đã dừng theo yêu cầu."
                    m = _PROGRESS_RE.findall(_tail(log, 400))
                    if m and int(m[-1]) != last:
                        last = min(int(m[-1]), 100)
                        job.set_progress(last, 100)
                    time.sleep(0.5)
            out = tmpd / "out.json"
            if proc.returncode != 0 or not out.exists():
                raise EditError("whisper.cpp không chạy được: " + _tail(log))
            raw = json.loads(out.read_text(encoding="utf-8", errors="replace"))
        dur = probe_media(folder / ORIGINAL)["duration"]
        cues = clean_cues(parse_whisper_json(raw), dur)
        data = {"language": lang, "model": Path(t["whisper"]["model"]).name, "source": "voice" if use_voice else "video",
                "created_at": datetime.now(timezone.utc).isoformat(), "cues": cues}
        _write_json(folder / SUBS_FILE, data)
        job.set_progress(100, 100)
        if not cues:
            return "Phiên âm xong nhưng không nhận ra lời nói nào (video có thể chỉ có nhạc). Bạn có thể tự thêm phụ đề."
        return f"Đã phiên âm {len(cues)} dòng phụ đề. Xem lại và sửa trước khi xuất video."
    finally:
        _busy.release()


# ---------- tạo phụ đề ASS và xuất video ----------
def _ass_time(sec: float) -> str:
    cs = int(round(sec * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _ass_text(text: str) -> str:
    text = text.replace("\\", "/").replace("{", "(").replace("}", ")")
    return "\\N".join(line for line in text.split("\n"))


def build_ass(cues: list[dict], s: dict) -> str:
    align, margin_v = ALIGN[s["position"]]
    font = config.get("EDIT_FONT", "Arial") or "Arial"
    col = COLORS[s["color"]]
    if s["box"]:
        border, outline, shadow, outline_col, back = 3, 14, 0, "&H8C000000", "&H8C000000"
    else:
        border, outline, shadow, outline_col, back = 1, 5, 2, "&H00000000", "&H80000000"
    head = (
        "[Script Info]\nScriptType: v4.00+\nWrapStyle: 0\nScaledBorderAndShadow: yes\n"
        f"PlayResX: {OUT_W}\nPlayResY: {OUT_H}\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font},{FONT_SIZES[s['size']]},{col},&H000000FF,{outline_col},{back},-1,0,0,0,100,100,0,0,{border},{outline},{shadow},{align},80,80,{margin_v},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    lines = [f"Dialogue: 0,{_ass_time(c['start'])},{_ass_time(c['end'])},Default,,0,0,0,,{_ass_text(c['text'])}" for c in cues]
    return head + "\n".join(lines) + "\n"


def build_filter(src: dict, s: dict, voice: bool, ass: bool) -> tuple[str, list[str]]:
    """Trả về (filter_complex, các tham số -map). src là kết quả probe_media của video gốc."""
    framing = s["framing"]
    if framing == "auto":
        ratio = src["width"] / src["height"] if src["width"] and src["height"] else 0
        framing = "scale" if ratio and abs(ratio - 9 / 16) < 0.03 else "fit"
    if framing == "crop":
        vf = f"[0:v]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,crop={OUT_W}:{OUT_H},setsar=1[vf]"
    elif framing == "scale":
        vf = f"[0:v]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease,pad={OUT_W}:{OUT_H}:(ow-iw)/2:(oh-ih)/2:black,setsar=1[vf]"
    else:   # fit: video nằm giữa, phía trên/dưới là chính nó phóng to và làm mờ
        vf = (f"[0:v]split=2[bg0][fg0];[bg0]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,gblur=sigma=8,"
              f"scale={OUT_W}:{OUT_H},eq=brightness=-0.08[bg];[fg0]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease[fg];"
              "[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[vf]")
    vf += ";[vf]subtitles=subs.ass[v]" if ass else ";[vf]null[v]"
    norm = ",loudnorm=I=-16:TP=-1.5:LRA=11" if s["loudnorm"] else ""
    maps = ["-map", "[v]"]
    parts = [vf]
    if src["has_audio"] and voice:
        parts.append(f"[0:a]volume={s['orig_volume'] / 100:.2f}[o];[1:a]volume={s['voice_volume'] / 100:.2f}[vo];"
                     f"[o][vo]amix=inputs=2:duration=first:dropout_transition=0:normalize=0{norm}[a]")
        maps += ["-map", "[a]"]
    elif voice:
        parts.append(f"[1:a]volume={s['voice_volume'] / 100:.2f}{norm}[a]")
        maps += ["-map", "[a]"]
    elif src["has_audio"]:
        parts.append(f"[0:a]anull{norm}[a]")
        maps += ["-map", "[a]"]
    return ";".join(parts), maps


_TIME_RE = re.compile(r"out_time_(?:us|ms)=(\d+)")


def render_job(job, rel: str, settings: dict | None = None) -> str:
    if not _busy.acquire(blocking=False):
        raise EditError("Đang có một tác vụ chỉnh sửa khác chạy. Đợi nó xong rồi thử lại.")
    try:
        t = tools(refresh=True)
        if not t["ffmpeg"]["ok"]:
            raise EditError(t["ffmpeg"]["problem"])
        s = clean_settings(settings)
        folder = library.resolve(rel)
        if is_scheduled(folder):
            raise EditError("Video này đã lên lịch (Facebook đã nhận bản cũ). Huỷ lịch trước, chỉnh sửa xong rồi hẹn lại.")
        src_path = folder / ORIGINAL
        src = probe_media(src_path)
        if not src["width"]:
            raise EditError("Không đọc được video gốc.")
        cues = clean_cues(load_subs(folder)["cues"], src["duration"]) if s["subs"] else []
        if s["subs"] and not cues:
            s["subs"] = False
            job.log("Chưa có phụ đề nên xuất không kèm phụ đề.")
        if s["subs"] and not t["ffmpeg"]["libass"]:
            raise EditError(t["ffmpeg"]["problem"])
        voice = voice_file(folder)
        fc, maps = build_filter(src, s, voice is not None, bool(cues))
        job.log(f"Xuất video {OUT_W}x{OUT_H}" + (f", {len(cues)} dòng phụ đề" if cues else "") + (f", kèm giọng đọc {voice.name}" if voice else "") + "...")
        with tempfile.TemporaryDirectory(prefix="mvt-render-") as tmp:
            tmpd = Path(tmp)
            if cues:
                (tmpd / "subs.ass").write_text(build_ass(cues, s), encoding="utf-8")
            out_tmp = folder / "video.draft.render.tmp.mp4"
            cmd = [t["ffmpeg"]["path"], "-nostdin", "-v", "error", "-nostats", "-y", "-i", str(src_path)]
            if voice:
                cmd += ["-i", str(voice)]
            cmd += ["-filter_complex", fc, *maps, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-movflags", "+faststart", "-progress", "pipe:1"]
            if src["duration"]:
                cmd += ["-t", f"{src['duration']:.3f}"]
            cmd.append(str(out_tmp))
            errf = tmpd / "ffmpeg.err"
            try:
                with open(errf, "w") as ef:
                    proc = subprocess.Popen(cmd, cwd=tmp, stdout=subprocess.PIPE, stderr=ef, text=True)
                    for line in proc.stdout:   # type: ignore[union-attr]
                        if job.cancelled:
                            _stop(proc)
                            out_tmp.unlink(missing_ok=True)
                            return "Đã dừng theo yêu cầu."
                        m = _TIME_RE.match(line.strip())
                        if m and src["duration"]:
                            job.set_progress(min(99, int(int(m[1]) / 1_000_000 / src["duration"] * 100)), 100)
                    proc.wait()
            except OSError as exc:
                raise EditError(f"Không chạy được FFmpeg: {exc}") from exc
            if proc.returncode != 0 or not out_tmp.exists() or out_tmp.stat().st_size == 0:
                out_tmp.unlink(missing_ok=True)
                raise EditError("FFmpeg báo lỗi: " + (_tail(errf) or f"mã {proc.returncode}"))
        out_tmp.replace(folder / DRAFT)
        _write_json(folder / SETTINGS_FILE, {"settings": s, "edited_at": datetime.now(timezone.utc).isoformat(), "voice": voice.name if voice else "",
                                              "cues": len(cues)})
        job.set_progress(100, 100)
        mb = (folder / DRAFT).stat().st_size / 1048576
        return f"Đã xuất bản nháp ({mb:.1f} MB). Xem thử rồi bấm Duyệt để thay video gốc; chưa duyệt thì hẹn giờ vẫn dùng video gốc."
    finally:
        _busy.release()
