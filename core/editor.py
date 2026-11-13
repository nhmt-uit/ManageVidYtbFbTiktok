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

from . import audioscan, bars, config, cutplan, hooks, library, origsubs, reelcheck, translate
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
    "box": True,             # nền mờ phía sau chữ
    "orig_volume": 25,       # % âm lượng video gốc khi có giọng đọc
    "voice_volume": 100,     # % âm lượng giọng đọc
    "loudnorm": True,        # chuẩn hóa âm lượng về mức Reels hay dùng
    "hide_orig": True,       # làm mờ sub in cứng có sẵn trong video (cần dò trước, xem origsubs.py; chưa dò thì xuất không che)
    "audio_clean": "off",    # off | light | voice: làm sạch âm thanh của video gốc (không áp cho giọng đọc thêm vào)
    "trim_bars": True,       # tự cắt viền đen có sẵn quanh hình trong video gốc trước khi phóng lên 1080x1920 (xem bars.py)
    "hook": True,            # in chữ hook đã duyệt ở 3 giây đầu (xem hooks.py; chưa duyệt hook thì bỏ qua)
    "quality": "standard",   # fast | standard | high: chất lượng hình và âm thanh khi xuất
    "cut": True,             # chỉ giữ các đoạn trong cuts.json khi xuất (cắt ngắn video dài, xem cutplan.py; chưa có đoạn thì xuất nguyên)
    # hiệu ứng (mặc định tắt)
    "fade": False,           # mờ dần hình + tiếng ở đầu và cuối video
    "transition": "none",    # chuyển cảnh giữa các đoạn cắt (cần bật Cắt ngắn và có từ 2 đoạn)
    "zoom": "off",           # off | in | out: zoom chậm suốt video
    "grade": "off",          # chỉnh màu, xem GRADES
    "mirror": False,         # lật ngang hình (phụ đề, hook vẫn đúng chiều)
    "speed": 100,            # % tốc độ phát (giữ cao độ giọng)
}
CHOICES = {"framing": ("auto", "scale", "fit", "crop"), "position": ("bottom", "middle", "top", "orig"),   # orig = đúng chỗ sub gốc
           "size": ("small", "medium", "large"), "color": ("white", "yellow", "cyan"),
           "audio_clean": ("off", "light", "voice"), "quality": ("fast", "standard", "high"),
           "transition": ("none", "fade", "slide", "flash", "black"), "zoom": ("off", "in", "out"),
           "grade": ("off", "bright", "vivid", "warm", "cool", "contrast")}
SPEEDS = (100, 105, 110, 115, 120, 125)
# chuyển cảnh: tên hiệu ứng của bộ lọc xfade. Chuyển cảnh không làm đổi độ dài: đoạn trước được kéo dài thêm TRANSITION_SEC
# (lấy phần ngay sau nó trong video gốc) để chồng lên đầu đoạn sau, nên phụ đề vẫn khớp giờ.
TRANSITIONS = {"fade": "fade", "slide": "slideleft", "flash": "fadewhite", "black": "fadeblack"}
TRANSITION_SEC = 0.4
GRADES = {"off": "",
          "bright": "eq=brightness=0.04:contrast=1.05:saturation=1.1",
          "vivid": "eq=contrast=1.08:saturation=1.35",
          "warm": "colorchannelmixer=rr=1.08:gg=1.02:bb=0.9,eq=saturation=1.08",
          "cool": "colorchannelmixer=rr=0.92:bb=1.08",
          "contrast": "eq=contrast=1.2:brightness=-0.02:saturation=1.05"}
ZOOM_AMOUNT = 0.08       # zoom chậm: 100% -> 108% (hoặc ngược lại) suốt video
FADE_IN, FADE_OUT = 0.4, 0.6
# audio_clean: light = cắt tiếng ù thấp + giảm ồn nền; voice = thêm làm rõ giọng nói (tăng dải 3 kHz, nén nhẹ cho đều tiếng)
AUDIO_CLEAN = {"off": "",
               "light": "highpass=f=80,afftdn=nf=-28",
               "voice": "highpass=f=90,lowpass=f=13000,afftdn=nf=-25,equalizer=f=3000:t=q:w=1:g=3,acompressor=threshold=0.1:ratio=3:attack=10:release=250"}
QUALITY = {"fast": (23, "128k"), "standard": (20, "160k"), "high": (17, "192k")}   # (crf x264, bitrate âm thanh)
MAX_SECONDS = 90   # nên đăng Reels/Shorts/TikTok dưới mức này
FONT_SIZES = {"small": 54, "medium": 66, "large": 80}
COLORS = {"white": "&H00FFFFFF", "yellow": "&H0000E6FF", "cyan": "&H00FFE600"}   # ASS dùng thứ tự BGR
ALIGN = {"bottom": (2, 330), "middle": (5, 0), "top": (8, 260), "orig": (5, 0)}                    # (Alignment, MarginV)

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


def _rate(v) -> float:
    """"30000/1001" -> 29.97; 0 nếu không đọc được."""
    try:
        a, _, b = str(v or "").partition("/")
        f = float(a) / float(b or 1)
    except (ValueError, ZeroDivisionError):
        return 0.0
    return f if 0 < f < 1000 else 0.0


def probe_media(path: Path) -> dict:
    """{"width", "height", "duration", "has_audio"} (0/False nếu không đọc được)."""
    out = {"width": 0, "height": 0, "duration": 0.0, "has_audio": False, "fps": 0.0}
    exe = tools()["ffprobe"]
    if not exe or not path.exists():
        return out
    try:
        r = _run([exe, "-v", "error", "-show_entries", "stream=codec_type,width,height,duration,avg_frame_rate,r_frame_rate:format=duration", "-of", "json", str(path)], 30)
        data = json.loads(r.stdout or "{}")
    except (OSError, subprocess.SubprocessError, ValueError):
        return out
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and not out["width"]:
            out["width"], out["height"] = int(s.get("width") or 0), int(s.get("height") or 0)
            out["fps"] = _rate(s.get("avg_frame_rate")) or _rate(s.get("r_frame_rate"))
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
    for k in ("subs", "box", "loudnorm", "hide_orig", "hook", "trim_bars", "cut", "fade", "mirror"):
        if isinstance(raw.get(k), bool):
            s[k] = raw[k]
    try:
        sp = int(raw.get("speed", s["speed"]))
        s["speed"] = sp if sp in SPEEDS else s["speed"]
    except (TypeError, ValueError):
        pass
    for k, lo, hi in (("orig_volume", 0, 200), ("voice_volume", 0, 300)):
        try:
            s[k] = max(lo, min(hi, int(raw.get(k, s[k]))))
        except (TypeError, ValueError):
            pass
    return s


def _clean_text(value) -> str:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(value or ""))
    return "\n".join(line.strip() for line in text.replace("\r", "").split("\n") if line.strip())[:MAX_CUE_CHARS].strip()


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
        text = _clean_text(c.get("text", ""))
        src = _clean_text(c.get("src", ""))   # câu gốc (trước khi dịch), chỉ để đối chiếu; video chỉ in `text`
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
        cue = {"start": round(start, 2), "end": round(end, 2), "text": text}
        if src and src != text:
            cue["src"] = src
        out.append(cue)
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
    if _busy.locked():   # đang phiên âm/dịch/xuất/duyệt: ghi chen vào sẽ bị tác vụ đó ghi đè hoặc làm hỏng file đầu vào
        raise EditError("Đang có tác vụ chỉnh sửa chạy. Đợi nó xong rồi thử lại.")
    dur = probe_media(folder / ORIGINAL)["duration"]
    clean = clean_cues(cues, dur)
    data = load_subs(folder)
    data.update(cues=clean, edited_at=datetime.now(timezone.utc).isoformat())
    _write_json(folder / SUBS_FILE, data)
    return {"cues": clean}


# ---------- giọng đọc ----------
def save_voice(rel: str, filename: str, stream, length: int | None) -> dict:
    folder = library.resolve(rel)
    if _busy.locked():   # đang phiên âm/dịch/xuất/duyệt: ghi chen vào sẽ bị tác vụ đó ghi đè hoặc làm hỏng file đầu vào
        raise EditError("Đang có tác vụ chỉnh sửa chạy. Đợi nó xong rồi thử lại.")
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


def _remove_voice_files(folder: Path) -> None:
    for ext in VOICE_EXTS:
        (folder / f"{VOICE_STEM}{ext}").unlink(missing_ok=True)


def remove_voice(rel: str) -> None:
    folder = library.resolve(rel)
    if _busy.locked():   # đang phiên âm/dịch/xuất/duyệt: ghi chen vào sẽ bị tác vụ đó ghi đè hoặc làm hỏng file đầu vào
        raise EditError("Đang có tác vụ chỉnh sửa chạy. Đợi nó xong rồi thử lại.")
    _remove_voice_files(folder)


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
              "stale": subs.get("edited_at", subs.get("created_at", "")) > info.get("edited_at", "") if subs.get("cues") else False,
              "check": draft_check(draft)}
    settings = clean_settings(_read_json(folder / SETTINGS_FILE).get("settings"))
    return {"rel": rel, "tools": t, "source": src, "cues": subs["cues"], "language": subs.get("language", ""),
            "transcribed": bool(subs.get("created_at")), "voice": voice_info(folder), "draft": dr, "translate": {k: v for k, v in translate.settings().items() if k != "base"}, "translated_to": subs.get("translated_to", ""),
            "translator": subs.get("translator", ""),
            "approved": _read_json(folder / APPROVED).get("approved_at", ""), "settings": settings,
            "scheduled": is_scheduled(folder), "langs": LANGS, "busy": _busy.locked(), "origsubs": origsubs_info(folder),
            "audioscan": _read_json(folder / audioscan.FILE),
            "hooks": hook_info(folder), "claude": bool(hooks.find_claude()), "cuts": cuts_info(folder, src.get("duration") or 0),
            "max_seconds": MAX_SECONDS, "standard": reelcheck.STANDARD_NAME}


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
        chk = draft_check(draft)
        if chk["errors"]:
            raise EditError(f"Bản nháp chưa đạt chuẩn đăng {reelcheck.STANDARD_NAME} nên chưa duyệt được: " + " ".join(chk["errors"]))
        info_set = _read_json(folder / SETTINGS_FILE)
        settings = info_set.get("applied") or info_set.get("settings", {})   # ghi lại cái thực sự đã dùng cho video được duyệt
        os.replace(draft, folder / ORIGINAL)   # nguyên tử: video.mp4 luôn là một file đầy đủ
        for name in (SUBS_FILE, SETTINGS_FILE, origsubs.FILE, audioscan.FILE, hooks.FILE, cutplan.FILE):
            (folder / name).unlink(missing_ok=True)
        _remove_voice_files(folder)
        _write_json(folder / APPROVED, {"approved_at": datetime.now(timezone.utc).isoformat(), "settings": settings})
        if reelcheck.available():
            try:
                reelcheck.ensure(folder, force=True)
            except Exception:   # noqa: BLE001  kiểm tra Reels chỉ là phụ
                pass
        return f"Đã duyệt: bản chỉnh sửa đã thay thế video gốc ({info['width']}x{info['height']}, {info['duration']:.0f} giây)."
    finally:
        _busy.release()


def draft_check(path: Path) -> dict:
    """Kiểm tra bản nháp theo chuẩn chung (reelcheck.strict_check). Không có ffprobe thì coi là chưa kiểm tra được (chặn duyệt)."""
    try:
        r = reelcheck.strict_check(path)
    except RuntimeError as exc:
        return {"errors": [f"Không kiểm tra được bản nháp: {exc}"], "warnings": [], "checked": False}
    return {"errors": r["errors"], "warnings": r["warnings"], "duration": r["duration"], "w": r["w"], "h": r["h"], "checked": True}


# ---------- cắt ngắn video dài (các đoạn giữ lại, cuts.json) ----------
def cuts_info(folder: Path, duration: float) -> dict:
    return cutplan.info(_read_json(folder / cutplan.FILE), duration)


def save_cuts(rel: str, segments, enabled: bool | None = None) -> dict:
    """Lưu các đoạn giữ lại do người dùng sửa (source = manual). Danh sách rỗng = bỏ cắt."""
    folder = library.resolve(rel)
    if is_scheduled(folder):
        raise EditError("Video này đã lên lịch. Huỷ lịch trước rồi mới chỉnh sửa được.")
    if _busy.locked():
        raise EditError("Đang có tác vụ chỉnh sửa khác chạy, đợi xong rồi thử lại.")
    dur = probe_media(folder / ORIGINAL)["duration"]
    segs = cutplan.clean_segments(segments, dur)
    if segs and cutplan.total(segs) < cutplan.MIN_TOTAL:
        raise EditError(f"Tổng các đoạn giữ lại phải ít nhất {cutplan.MIN_TOTAL:g} giây.")
    cur = _read_json(folder / cutplan.FILE)
    if not segs:
        (folder / cutplan.FILE).unlink(missing_ok=True)
    else:
        _write_json(folder / cutplan.FILE, {"segments": segs, "source": "manual", "summary": cur.get("summary", "") if isinstance(cur, dict) else "",
                                            "updated_at": cutplan.now()})
    return cuts_info(folder, dur)


def suggest_cuts_job(job, rel: str, notes: str = "") -> str:
    """Nhờ Claude Code đề xuất các đoạn giữ lại cho video dài (dựa vào phụ đề có mốc thời gian). Chỉ ghi cuts.json, không đụng video."""
    if not _busy.acquire(blocking=False):
        raise EditError("Đang có một tác vụ chỉnh sửa khác chạy. Đợi nó xong rồi thử lại.")
    try:
        folder = library.resolve(rel)
        if is_scheduled(folder):
            raise EditError("Video này đã lên lịch. Huỷ lịch trước rồi mới chỉnh sửa được.")
        dur = probe_media(folder / ORIGINAL)["duration"]
        cues = clean_cues(load_subs(folder)["cues"], dur)
        job.log(f"Đang nhờ Claude chọn các đoạn giữ lại (video {dur:.0f} giây, {len(cues)} dòng phụ đề; khoảng 20 đến 90 giây)...")
        try:
            r = cutplan.suggest(folder.name, cues, dur, notes, cancelled=lambda: job.cancelled, model=config.get("HOOK_MODEL", "") or "")
        except cutplan.CutError as exc:
            raise EditError(str(exc)) from exc
        _write_json(folder / cutplan.FILE, {"segments": r["segments"], "source": "claude", "summary": r["summary"], "updated_at": cutplan.now()})
        return (f"Claude đề xuất giữ {len(r['segments'])} đoạn, tổng {cutplan.total(r['segments']):.0f} giây. "
                "Xem lại từng đoạn (bấm ▶ để nghe), sửa nếu cần, tick \"Cắt theo các đoạn này khi xuất\" rồi Xuất video.")
    finally:
        _busy.release()


# ---------- sub gốc (chữ in cứng trong video) ----------
def origsubs_info(folder: Path) -> dict:
    """Kết quả dò sub gốc đã lưu (đã làm sạch). found=False nếu chưa dò hoặc không có sub."""
    return origsubs.clean(_read_json(folder / origsubs.FILE))


def save_origsubs(rel: str, data: dict) -> dict:
    """Lưu vùng che do người dùng chỉnh tay (band: x, y, w, h là tỉ lệ 0..1) và kiểu che (mode)."""
    folder = library.resolve(rel)
    cur = origsubs_info(folder)
    if isinstance(data.get("band"), dict):
        cur["band"] = data["band"]
        cur["found"] = True
    if data.get("mode") in origsubs.MODES:
        cur["mode"] = data["mode"]
    new = origsubs.clean(cur)
    if not new["found"]:
        raise EditError("Vùng che không hợp lệ (quá nhỏ hoặc nằm ngoài khung hình).")
    _write_json(folder / origsubs.FILE, new)
    return new


def detect_origsubs_job(job, rel: str) -> str:
    if not _busy.acquire(blocking=False):
        raise EditError("Đang có một tác vụ chỉnh sửa khác chạy. Đợi nó xong rồi thử lại.")
    try:
        t = tools(refresh=True)
        if not t["ffmpeg"]["ok"]:
            raise EditError(t["ffmpeg"]["problem"])
        folder = library.resolve(rel)
        src = probe_media(folder / ORIGINAL)
        if not src["width"]:
            raise EditError("Không đọc được video.")
        job.log("Đang dò chữ phụ đề in sẵn trong hình...")
        try:
            res = origsubs.detect(t["ffmpeg"]["path"], folder / ORIGINAL, src["duration"], src["width"], src["height"],
                                  progress=job.set_progress, cancelled=lambda: job.cancelled)
        except origsubs.DetectError as exc:
            raise EditError(str(exc)) from exc
        if res.get("found"):
            res["band"] = origsubs.default_band(res["band"])   # mặc định cao 10%, rộng 90% quanh chỗ sub gốc
        res = origsubs.clean(res)
        _write_json(folder / origsubs.FILE, res)
        if not res["found"]:
            return "Không thấy sub in cứng trong video này (hoặc chữ quá mờ). Nếu video có sub, bạn vẫn tự khoanh vùng che được ở bước này."
        b = res["band"]
        total = sum(z - a for a, z in res["ranges"])
        return (f"Đã dò sub gốc: {len(res['ranges'])} khoảng có sub (tổng {total:.0f} giây), vùng che cách mép trên {b['y'] * 100:.0f}% và cao {b['h'] * 100:.0f}%. "
                "Xem khung đứt nét trên video, chỉnh nếu cần rồi tick \"Che sub gốc khi xuất\".")
    finally:
        _busy.release()


def hook_info(folder: Path) -> dict:
    return hooks.clean(_read_json(folder / hooks.FILE))


def save_hook(rel: str, text) -> dict:
    """Lưu (hoặc bỏ, nếu text rỗng) chữ hook người dùng đã duyệt. Người dùng được sửa tự do trước khi duyệt."""
    folder = library.resolve(rel)
    cur = hook_info(folder)
    t = hooks.clean_text(text)
    cur["approved"] = {"text": t, "seconds": hooks.HOOK_SECONDS} if t else None
    _write_json(folder / hooks.FILE, cur)
    return cur


def hook_generate_job(job, rel: str, notes: str = "") -> str:
    """Nhờ Claude Code (claude -p) đề xuất hook và câu trend từ tên video + phụ đề. Không đụng video, chỉ ghi hooks.json."""
    if not _busy.acquire(blocking=False):
        raise EditError("Đang có một tác vụ chỉnh sửa khác chạy. Đợi nó xong rồi thử lại.")
    try:
        folder = library.resolve(rel)
        src = probe_media(folder / ORIGINAL)
        subs = load_subs(folder)
        title = folder.name
        if not subs["cues"]:
            job.log("Chưa có phụ đề nên Claude chỉ dựa vào tên video; nên phiên âm trước để hook sát nội dung.")
        job.log("Đang nhờ Claude đề xuất hook (khoảng 20 đến 60 giây)...")
        try:
            props = hooks.generate(hooks.build_prompt(title, subs["cues"], src["duration"], subs.get("language", ""), notes),
                                   cancelled=lambda: job.cancelled, model=config.get("HOOK_MODEL", "") or "")
        except hooks.HookError as exc:
            raise EditError(str(exc)) from exc
        cur = hook_info(folder)
        cur.update(proposals=props, generated_at=hooks.now())
        _write_json(folder / hooks.FILE, cur)
        return f"Claude đã đề xuất {len(props['hooks'])} hook. Chọn một câu, sửa nếu muốn rồi bấm Duyệt hook."
    finally:
        _busy.release()


def scan_audio_job(job, rel: str) -> str:
    """Đo âm thanh video gốc và lưu gợi ý chế độ làm sạch vào audioscan.json."""
    if not _busy.acquire(blocking=False):
        raise EditError("Đang có một tác vụ chỉnh sửa khác chạy. Đợi nó xong rồi thử lại.")
    try:
        t = tools(refresh=True)
        if not t["ffmpeg"]["ok"]:
            raise EditError(t["ffmpeg"]["problem"])
        folder = library.resolve(rel)
        src = probe_media(folder / ORIGINAL)
        job.log("Đang đo âm thanh (độ ồn nền, tiếng ù, tiếng xì, độ lớn)...")
        try:
            res = audioscan.scan(t["ffmpeg"]["path"], folder / ORIGINAL, has_audio=src["has_audio"])
        except audioscan.ScanError as exc:
            raise EditError(str(exc)) from exc
        _write_json(folder / audioscan.FILE, res)
        names = {"off": "Tắt", "light": "Nhẹ", "voice": "Rõ giọng nói"}
        return "Đã phân tích âm thanh. Gợi ý: " + names[res["recommend"]] + ". " + " ".join(res["reasons"][-1:])
    finally:
        _busy.release()


def _framing_transform(src: dict, framing: str) -> tuple[float, float, float]:
    """(hệ số phóng, lệch x, lệch y) khi đưa video gốc vào khung 1080x1920 theo kiểu khung hình `framing` (đã giải quyết 'auto')."""
    w, h = src["width"], src["height"]
    if framing == "auto":
        framing = "crop" if abs(w / h - 9 / 16) < 0.03 else "fit"
    f = max(OUT_W / w, OUT_H / h) if framing == "crop" else min(OUT_W / w, OUT_H / h)
    return f, (OUT_W - w * f) / 2, (OUT_H - h * f) / 2


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


# ---------- dịch phụ đề ----------
def translate_job(job, rel: str, to: str = "vi") -> str:
    """Dịch toàn bộ dòng phụ đề sang ngôn ngữ `to`. Câu gốc được giữ trong trường src để đối chiếu hoặc hoàn tác."""
    if not _busy.acquire(blocking=False):
        raise EditError("Đang có một tác vụ chỉnh sửa khác chạy. Đợi nó xong rồi thử lại.")
    try:
        if to not in translate.TARGETS:
            to = "vi"
        folder = library.resolve(rel)
        data = load_subs(folder)
        cues = clean_cues(data["cues"], 0.0)
        if not cues:
            raise EditError("Chưa có phụ đề để dịch. Phiên âm trước hoặc tự thêm dòng.")
        cfg = translate.settings()
        if not cfg["ok"]:
            raise EditError(cfg["problem"])
        source = str(data.get("language") or "")
        if source == to:
            raise EditError("Phụ đề đã ở đúng ngôn ngữ cần dịch.")
        originals = [c.get("src") or c["text"] for c in cues]
        job.log(f"Dịch {len(cues)} dòng bằng {cfg['label']} ({cfg['model']})...")
        try:
            result = translate.translate_lines(originals, source if source in translate.SOURCES else "auto", to,
                                               progress=job.set_progress, cancelled=lambda: job.cancelled)
        except translate.TranslateError as exc:
            if job.cancelled:
                return "Đã dừng theo yêu cầu. Phụ đề giữ nguyên."
            raise EditError(str(exc)) from exc
        new = []
        for c, orig, tr in zip(cues, originals, result):
            new.append({"start": c["start"], "end": c["end"], "text": _clean_text(tr) or orig, "src": orig})
        dur = probe_media(folder / ORIGINAL)["duration"]
        data.update(cues=clean_cues(new, dur), translated_to=to, translator=f"{cfg['label']} / {cfg['model']}",
                    edited_at=datetime.now(timezone.utc).isoformat())
        _write_json(folder / SUBS_FILE, data)
        job.set_progress(100, 100)
        return f"Đã dịch {len(new)} dòng sang {translate.TARGETS[to]}. Đọc lại và sửa trước khi xuất (AI có thể dịch sai tên riêng hay thuật ngữ)."
    finally:
        _busy.release()


# ---------- tạo phụ đề ASS và xuất video ----------
def _ass_time(sec: float) -> str:
    cs = int(round(sec * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _ass_text(text: str) -> str:
    text = text.replace("\\", "/").replace("{", "(").replace("}", ")")
    return "\\N".join(line for line in text.split("\n"))


def build_ass(cues: list[dict], s: dict, center_y: float | None = None, hook: str = "", hook_end: float = 3.0) -> str:
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
        f"Style: Default,{font},{FONT_SIZES[s['size']]},{col},&H000000FF,{outline_col},{back},-1,0,0,0,100,100,0,0,{border},{outline},{shadow},{align},80,80,{margin_v},1\n"
        f"Style: Hook,{font},96,&H0000E6FF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,8,3,8,70,70,300,1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    tag = f"{{\\an5\\pos({OUT_W // 2},{int(center_y)})}}" if center_y is not None else ""   # đặt giữa vùng sub gốc
    lines = [f"Dialogue: 0,{_ass_time(c['start'])},{_ass_time(c['end'])},Default,,0,0,0,,{tag}{_ass_text(c['text'])}" for c in cues]
    if hook:   # chữ hook ở 3 giây đầu: hiện nhanh (phóng nhẹ), mờ dần khi hết; tránh đè phụ đề nếu phụ đề đặt ở trên
        y = 520 if s["position"] == "top" else 330
        lines.insert(0, f"Dialogue: 1,{_ass_time(0)},{_ass_time(hook_end)},Hook,,0,0,0,,"
                        f"{{\\an8\\pos({OUT_W // 2},{y})\\fscx70\\fscy70\\fad(100,250)\\t(0,200,\\fscx100\\fscy100)}}{_ass_text(hook)}")
    return head + "\n".join(lines) + "\n"


def transition_len(segs: list[dict], duration: float) -> float:
    """Độ dài chuyển cảnh dùng được cho các đoạn này (0 = không làm được). Đoạn trước kéo dài thêm chừng ấy giây
    nên cần còn hình phía sau nó trong video gốc, và không dài hơn đoạn ngắn nhất."""
    if len(segs) < 2:
        return 0.0
    d = min([TRANSITION_SEC] + [s["end"] - s["start"] for s in segs]
            + ([duration - s["end"] for s in segs[:-1]] if duration else []))
    return round(d, 3) if d >= 0.15 else 0.0


def _cut_chain(inp: str, out: str, segs: list[dict], audio: bool, xfade: str = "", xlen: float = 0.0) -> str:
    """Giữ các đoạn `segs` (giây, theo video gốc) của luồng [inp] rồi nối lại thành [out].
    xfade (chỉ cho hình): tên hiệu ứng chuyển cảnh; mỗi đoạn trừ đoạn cuối lấy dư `xlen` giây để chồng lên đầu đoạn sau,
    nên tổng độ dài và mốc giờ từng đoạn vẫn như khi nối thẳng."""
    trim, setpts, split, kind = ("atrim", "asetpts", "asplit", "v=0:a=1") if audio else ("trim", "setpts", "split", "v=1:a=0")
    n = len(segs)
    tag = "ca" if audio else "cv"
    tag += out
    fx = bool(xfade and xlen > 0 and n > 1 and not audio)
    parts = [f"[{inp}]{split}={n}" + "".join(f"[{tag}i{i}]" for i in range(n))] if n > 1 else []
    for i, sg in enumerate(segs):
        src = f"{tag}i{i}" if n > 1 else inp
        end = sg["end"] + (xlen if fx and i < n - 1 else 0)
        parts.append(f"[{src}]{trim}=start={sg['start']:.3f}:end={end:.3f},{setpts}=PTS-STARTPTS[{tag}o{i}]")
    if fx:
        acc, prev = 0.0, f"{tag}o0"
        for i in range(1, n):
            acc += segs[i - 1]["end"] - segs[i - 1]["start"]
            lab = out if i == n - 1 else f"{tag}x{i}"
            parts.append(f"[{prev}][{tag}o{i}]xfade=transition={xfade}:duration={xlen:.3f}:offset={acc:.3f}[{lab}]")
            prev = lab
        return ";".join(parts)
    parts.append("".join(f"[{tag}o{i}]" for i in range(n)) + f"concat=n={n}:{kind}[{out}]")
    return ";".join(parts)


def out_fps(src: dict) -> int:
    """Số khung hình/giây của bản xuất khi phải đặt lại (đổi tốc độ): theo video gốc, trong khoảng 24-60."""
    f = src.get("fps") or 30
    return int(max(24, min(60, round(f))))


def build_filter(src: dict, s: dict, voice: bool, ass: bool, cover: str = "", crop: dict | None = None,
                 segs: list[dict] | None = None, dur: float = 0.0, xlen: float = 0.0) -> tuple[str, list[str]]:
    """Trả về (filter_complex, các tham số -map). src là kết quả probe_media của video gốc.
    cover: đoạn filter che sub gốc (origsubs.cover_chain, đầu ra là [src]); rỗng = không che.
    crop: vùng hình cần giữ (bars.detect) để cắt viền đen có sẵn; src phải là kích thước SAU khi cắt.
    segs: các đoạn giữ lại (cắt ngắn video). Che sub gốc làm TRƯỚC khi cắt vì khoảng che tính theo giờ của video gốc.
    dur: độ dài video sau khi cắt, TRƯỚC khi đổi tốc độ (cho zoom, mờ dần). xlen: độ dài chuyển cảnh (transition_len).
    Thứ tự hình: che sub -> cắt viền -> cắt đoạn (+chuyển cảnh) -> khung 9:16 -> lật -> màu -> zoom -> tốc độ -> phụ đề -> mờ đầu/cuối.
    Phụ đề (subs.ass) phải tính theo giờ SAU khi đổi tốc độ."""
    speed = s.get("speed", 100) / 100
    dur_out = dur / speed if dur else 0.0
    vin = "src" if cover else "0:v"
    pre = [cover] if cover else []
    if crop:
        pre.append(f"[{vin}]crop={crop['w']}:{crop['h']}:{crop['x']}:{crop['y']}[cb]")
        vin = "cb"
    ain, voin = "0:a", "1:a"
    if segs:
        xf = TRANSITIONS.get(s.get("transition", "none"), "")
        pre.append(_cut_chain(vin, "vcut", segs, audio=False, xfade=xf, xlen=xlen))
        vin = "vcut"
        if src["has_audio"]:
            pre.append(_cut_chain("0:a", "acut", segs, audio=True))
            ain = "acut"
        if voice:   # giọng đọc thu theo giờ của video gốc: cắt cùng các đoạn để không lệch
            pre.append(_cut_chain("1:a", "vocut", segs, audio=True))
            voin = "vocut"
    framing = s["framing"]
    if framing == "auto":
        ratio = src["width"] / src["height"] if src["width"] and src["height"] else 0
        framing = "crop" if ratio and abs(ratio - 9 / 16) < 0.03 else "fit"
    if framing == "crop":
        vf = f"[{vin}]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,crop={OUT_W}:{OUT_H},setsar=1[vf]"
    elif framing == "scale":
        vf = f"[{vin}]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease,pad={OUT_W}:{OUT_H}:(ow-iw)/2:(oh-ih)/2:black,setsar=1[vf]"
    else:   # fit: video nằm giữa, phía trên/dưới là chính nó phóng to và làm mờ
        vf = (f"[{vin}]split=2[bg0][fg0];[bg0]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,gblur=sigma=8,"
              f"scale={OUT_W}:{OUT_H},eq=brightness=-0.08[bg];[fg0]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease[fg];"
              "[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[vf]")
    if pre:
        vf = ";".join(pre) + ";" + vf
    look = []
    if s.get("mirror"):
        look.append("hflip")
    if GRADES.get(s.get("grade", "off")):
        look.append(GRADES[s["grade"]])
    if s.get("zoom") in ("in", "out") and dur > 0:
        p = f"min(t/{dur:.3f},1)" if s["zoom"] == "in" else f"(1-min(t/{dur:.3f},1))"
        z = f"(1+{ZOOM_AMOUNT}*{p})"
        # phóng to từng khung (kích thước chẵn) rồi cắt giữa về 1080x1920
        look.append(f"scale=w='trunc({OUT_W}*{z}/2)*2':h='trunc({OUT_H}*{z}/2)*2':eval=frame,crop={OUT_W}:{OUT_H},setsar=1")
    if speed != 1:
        look.append(f"setpts=PTS/{speed:.2f},fps={out_fps(src)}")
    if look:
        vf += ";[vf]" + ",".join(look) + "[vl]"
        vlast = "vl"
    else:
        vlast = "vf"
    fade_ok = s.get("fade") and dur_out > FADE_IN + FADE_OUT + 1
    vfade = f"fade=t=in:st=0:d={FADE_IN},fade=t=out:st={dur_out - FADE_OUT:.3f}:d={FADE_OUT}" if fade_ok else ""
    if ass:
        vf += f";[{vlast}]subtitles=subs.ass" + ("," + vfade if vfade else "") + "[v]"
    else:
        vf += f";[{vlast}]" + (vfade or "null") + "[v]"
    norm = ",loudnorm=I=-16:TP=-1.5:LRA=11" if s["loudnorm"] else ""
    if speed != 1:
        norm = f",atempo={speed:.2f}" + norm   # đổi tốc độ tiếng, giữ cao độ
    if fade_ok:
        norm += f",afade=t=in:st=0:d={FADE_IN},afade=t=out:st={dur_out - FADE_OUT:.3f}:d={FADE_OUT}"
    clean = AUDIO_CLEAN[s["audio_clean"]]
    clean = clean + "," if clean else ""   # nối trước volume/anull của âm thanh video gốc
    maps = ["-map", "[v]"]
    parts = [vf]
    if src["has_audio"] and voice:
        parts.append(f"[{ain}]{clean}volume={s['orig_volume'] / 100:.2f}[o];[{voin}]volume={s['voice_volume'] / 100:.2f}[vo];"
                     f"[o][vo]amix=inputs=2:duration=first:dropout_transition=0:normalize=0{norm}[a]")
        maps += ["-map", "[a]"]
    elif voice:
        parts.append(f"[{voin}]volume={s['voice_volume'] / 100:.2f}{norm}[a]")
        maps += ["-map", "[a]"]
    elif src["has_audio"]:
        parts.append(f"[{ain}]{clean}anull{norm}[a]")
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
        wanted = dict(s)   # lựa chọn của bạn; s bên dưới có thể bị tắt bớt (chưa có phụ đề, chưa dò sub gốc...) và là cái thực sự dùng
        folder = library.resolve(rel)
        if is_scheduled(folder):
            raise EditError("Video này đã lên lịch (Facebook đã nhận bản cũ). Huỷ lịch trước, chỉnh sửa xong rồi hẹn lại.")
        src_path = folder / ORIGINAL
        src = probe_media(src_path)
        if not src["width"]:
            raise EditError("Không đọc được video gốc.")
        if s["audio_clean"] != "off" and not _has_filter(t["ffmpeg"]["path"], "afftdn"):
            s["audio_clean"] = "off"
            job.log("FFmpeg này không có bộ lọc giảm ồn (afftdn) nên bỏ qua bước làm sạch âm thanh.")
        bar = None
        if s["trim_bars"]:
            job.log("Dò viền đen có sẵn trong video gốc...")
            bar = bars.detect(t["ffmpeg"]["path"], src_path, src["duration"], src["width"], src["height"], cancelled=lambda: job.cancelled)
            if bar:
                oi0 = origsubs_info(folder)
                if oi0["found"] and (s["hide_orig"] or s["position"] == "orig"):
                    # sub gốc có thể nằm trong chính vùng viền đen (ví dụ chữ in ở dải đen phía dưới): giữ lại phần đó, nếu không sub mới sẽ lệch khỏi chỗ sub cũ
                    bx, by, bw, bh = origsubs.pixel_rect(oi0, src["width"], src["height"])
                    pad = max(4, int(bh * 0.3))
                    x0, y0 = max(0, min(bar["x"], bx - pad)), max(0, min(bar["y"], by - pad))
                    x1, y1 = min(src["width"], max(bar["x"] + bar["w"], bx + bw + pad)), min(src["height"], max(bar["y"] + bar["h"], by + bh + pad))
                    x0, y0, x1, y1 = x0 - x0 % 2, y0 - y0 % 2, x1 + x1 % 2, y1 + y1 % 2
                    x1, y1 = min(src["width"], x1), min(src["height"], y1)
                    if (x0, y0, x1, y1) != (bar["x"], bar["y"], bar["x"] + bar["w"], bar["y"] + bar["h"]):
                        bar = {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0, "left": x0, "top": y0, "right": src["width"] - x1, "bottom": src["height"] - y1}
                        job.log("Sub gốc nằm ngoài vùng hình đã dò nên giữ thêm phần chứa sub gốc để phụ đề mới khớp đúng chỗ.")
                if bar["left"] or bar["right"] or bar["top"] or bar["bottom"]:
                    job.log(f"Cắt viền đen có sẵn: trái {bar['left']}, phải {bar['right']}, trên {bar['top']}, dưới {bar['bottom']} (điểm ảnh) rồi phóng to cho đầy khung.")
                else:
                    bar = None
        eff = dict(src, width=bar["w"], height=bar["h"]) if bar else src   # kích thước hình thật sau khi cắt viền đen
        segs = cuts_info(folder, src["duration"])["segments"] if s["cut"] else []
        if s["cut"] and not segs:
            s["cut"] = False
            job.log("Chưa lưu đoạn cắt nào nên xuất nguyên video.")
        out_dur = cutplan.total(segs) if segs else src["duration"]
        if segs:
            job.log(f"Cắt ngắn: giữ {len(segs)} đoạn, tổng {out_dur:.1f} giây (video gốc {src['duration']:.0f} giây).")
        xlen = 0.0
        if s["transition"] != "none":
            if len(segs) < 2:
                s["transition"] = "none"
                job.log("Chuyển cảnh chỉ dùng khi bật Cắt ngắn và có từ 2 đoạn trở lên nên bỏ qua.")
            elif not _has_filter(t["ffmpeg"]["path"], "xfade"):
                s["transition"] = "none"
                job.log("FFmpeg này không có bộ lọc chuyển cảnh (xfade, cần FFmpeg 4.3 trở lên) nên nối thẳng các đoạn.")
            else:
                xlen = transition_len(segs, src["duration"])
                if not xlen:
                    s["transition"] = "none"
                    job.log("Các đoạn cắt quá ngắn để làm chuyển cảnh nên nối thẳng.")
        speed = s["speed"] / 100
        cut_dur = out_dur          # độ dài sau khi cắt, trước khi đổi tốc độ
        out_dur = out_dur / speed if out_dur else out_dur
        if speed != 1:
            job.log(f"Tốc độ {s['speed']}%: video còn {out_dur:.1f} giây.")
        cues = clean_cues(load_subs(folder)["cues"], src["duration"]) if s["subs"] else []
        if segs and cues:
            cues = cutplan.retime_cues(cues, segs)
        if cues and speed != 1:
            cues = [{**c, "start": round(c["start"] / speed, 3), "end": round(c["end"] / speed, 3)} for c in cues]
        if s["subs"] and not cues:
            s["subs"] = False
            job.log("Chưa có phụ đề nên xuất không kèm phụ đề.")
        hook_text = ""
        if s["hook"]:
            ap = hook_info(folder)["approved"]
            hook_text = ap["text"] if ap else ""
            if not hook_text:
                s["hook"] = False
                job.log("Chưa duyệt hook nào nên xuất không kèm hook.")
        if (cues or hook_text) and not t["ffmpeg"]["libass"]:
            raise EditError(t["ffmpeg"]["problem"])
        oi = origsubs_info(folder)
        cover, center_y = "", None
        if s["hide_orig"] and not oi["found"]:   # mặc định bật: video chưa dò (hoặc không có) sub gốc thì xuất không che
            s["hide_orig"] = False
            job.log("Chưa dò sub gốc (hoặc video không có sub gốc) nên xuất không che.")
        if s["hide_orig"]:
            cover = origsubs.cover_chain(oi, src["width"], src["height"])
            job.log("Che sub gốc: " + ("chỉ trong các khoảng có sub." if oi["mode"] == "ranges" else "suốt video."))
        if s["hide_orig"] and s["subs"] and s["position"] != "orig":
            job.log(f"Lưu ý: vùng sub gốc được che nhưng phụ đề mới đặt ở vị trí \"{s['position']}\" nên sẽ không nằm đúng chỗ sub cũ. Muốn đè lên sub cũ, chọn vị trí \"Đúng chỗ sub gốc\".")
        if s["position"] == "orig":
            if oi["found"]:
                x, y, w, h = origsubs.pixel_rect(oi, src["width"], src["height"])
                f, _ox, oy = _framing_transform(eff, s["framing"])
                center_y = oy + (y + h / 2 - (bar["y"] if bar else 0)) * f
            else:
                job.log("Chưa dò sub gốc nên phụ đề mới đặt ở vị trí mặc định (dưới).")
                s["position"] = "bottom"
        voice = voice_file(folder)
        crf, abr = QUALITY[s["quality"]]
        long_note = ""
        if out_dur and out_dur > MAX_SECONDS + 0.5:
            long_note = (f" Lưu ý: bản xuất dài {out_dur:.0f} giây, vượt mức {MAX_SECONDS} giây nên KHÔNG duyệt được (không đăng được Reels)."
                         " Dùng bước Cắt ngắn để giữ các đoạn dưới 90 giây rồi xuất lại.")
            job.log(long_note.strip())
        if s["zoom"] != "off" and not cut_dur:
            s["zoom"] = "off"
            job.log("Không đọc được độ dài video nên bỏ qua zoom chậm.")
        if s["fade"] and out_dur <= FADE_IN + FADE_OUT + 1:
            s["fade"] = False
            job.log("Video quá ngắn nên bỏ qua mờ dần đầu/cuối.")
        fx = [x for x in (
            "mờ dần đầu/cuối" if s["fade"] else "",
            f"chuyển cảnh {s['transition']} {xlen:g} giây" if s["transition"] != "none" else "",
            {"in": "zoom chậm vào", "out": "zoom chậm ra"}.get(s["zoom"], ""),
            f"màu {s['grade']}" if s["grade"] != "off" else "",
            "lật ngang" if s["mirror"] else "",
            f"tốc độ {s['speed']}%" if speed != 1 else "") if x]
        if fx:
            job.log("Hiệu ứng: " + ", ".join(fx) + ".")
        if s["zoom"] != "off" and s["hide_orig"] and s["subs"] and s["position"] == "orig":
            job.log("Lưu ý: zoom chậm phóng cả vùng che sub gốc (tối đa 8%) còn phụ đề mới đứng yên, nên về cuối có thể lệch vài chục điểm ảnh so với vùng che.")
        fc, maps = build_filter(eff, s, voice is not None, bool(cues) or bool(hook_text), cover, bar, segs or None, cut_dur, xlen)
        job.log(f"Xuất video {OUT_W}x{OUT_H}" + (f", {len(cues)} dòng phụ đề" if cues else "") + (", kèm hook 3 giây đầu" if hook_text else "") + (f", kèm giọng đọc {voice.name}" if voice else "") + "...")
        with tempfile.TemporaryDirectory(prefix="mvt-render-") as tmp:
            tmpd = Path(tmp)
            if cues or hook_text:
                hook_end = min(hooks.HOOK_SECONDS, out_dur) if out_dur else hooks.HOOK_SECONDS
                (tmpd / "subs.ass").write_text(build_ass(cues, s, center_y, hook_text, hook_end), encoding="utf-8")
            out_tmp = folder / "video.draft.render.tmp.mp4"
            cmd = [t["ffmpeg"]["path"], "-nostdin", "-v", "error", "-nostats", "-y", "-i", str(src_path)]
            if voice:
                cmd += ["-i", str(voice)]
            cmd += ["-filter_complex", fc, *maps, "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", abr, "-ar", "44100", "-movflags", "+faststart", "-progress", "pipe:1"]
            if out_dur:
                cmd += ["-t", f"{out_dur:.3f}"]
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
                        if m and out_dur:
                            job.set_progress(min(99, int(int(m[1]) / 1_000_000 / out_dur * 100)), 100)
                    proc.wait()
            except OSError as exc:
                raise EditError(f"Không chạy được FFmpeg: {exc}") from exc
            if proc.returncode != 0 or not out_tmp.exists() or out_tmp.stat().st_size == 0:
                out_tmp.unlink(missing_ok=True)
                raise EditError("FFmpeg báo lỗi: " + (_tail(errf) or f"mã {proc.returncode}"))
        out_tmp.replace(folder / DRAFT)
        audio_report = ""
        if s["audio_clean"] != "off" and src["has_audio"] and not voice:   # có giọng đọc trộn vào thì so sánh không còn công bằng
            try:
                before = audioscan.scan(t["ffmpeg"]["path"], src_path, seconds=60)
                after = audioscan.scan(t["ffmpeg"]["path"], folder / DRAFT, seconds=60)
                audio_report = audioscan.compare(before, after)
                if audio_report:
                    job.log("Làm sạch âm thanh: " + audio_report)
            except (audioscan.ScanError, ValueError, OSError):
                pass
        # "settings" = lựa chọn của bạn (mở lại hộp thoại vẫn thấy đúng, ví dụ Che sub gốc vẫn bật để lần sau dò xong là dùng);
        # "applied" = cái thực sự dùng cho bản nháp này
        _write_json(folder / SETTINGS_FILE, {"settings": wanted, "applied": s, "edited_at": datetime.now(timezone.utc).isoformat(), "voice": voice.name if voice else "",
                                              "cues": len(cues), "audio_report": audio_report, "segments": segs})
        job.set_progress(100, 100)
        mb = (folder / DRAFT).stat().st_size / 1048576
        return f"Đã xuất bản nháp ({mb:.1f} MB). Xem thử rồi bấm Duyệt để thay video gốc; chưa duyệt thì hẹn giờ vẫn dùng video gốc." + long_note
    finally:
        _busy.release()
