"""Lồng tiếng từng câu phụ đề bằng giọng máy VieNeu (chạy trên máy, qua tools/vieneu_worker.py).

Mỗi câu một file giọng trong `_tts/` của video, nên sửa một câu chỉ cần đọc lại câu đó. Giọng được khóa theo
(giọng, chữ cần đọc): đổi giờ câu không phải đọc lại, đổi chữ thì câu đó thành "cần đọc lại".
Ghép xong ra `voice.wav` (giờ theo video gốc) = giọng đọc ở bước 3, nên cắt ngắn / tốc độ / âm lượng gốc dùng lại như cũ.

dub.json: {"voice", "say": {chữ phụ đề: chữ đọc}, "takes": {khóa: {"file", "voice", "text", "duration", "clarity", "speed", "made_at"}},
           "built_at", "built_sig"}
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import config, editor, library

FILE = "dub.json"
DIR = "_tts"
VOICE_OUT = "voice.wav"
WORKER = Path(__file__).resolve().parent.parent / "tools" / "vieneu_worker.py"
# nhịp đã duyệt (2026-11-18): bỏ khoảng lặng dài trong câu, đọc nhanh hơn 10%
POST_FILTER = ("silenceremove=start_periods=1:start_threshold=-42dB:stop_periods=-1:stop_duration=0.25:"
               "stop_threshold=-42dB:stop_silence=0.18,atempo=1.10,apad=pad_dur=0.05")
LEAD = 0.10        # giọng vào sau khi sub hiện 0,1 giây
GAP = 0.12         # tối thiểu giữa hai câu
AUTO_MAX = 1.25    # tự tăng tốc tối đa để vừa chỗ trống
SPEEDS = (0.8, 1.5)
MAX_ITEMS = 400
_voices_cache: dict = {}
_lock = threading.Lock()


def python_path() -> str:
    return str(Path(config.get("TTS_PYTHON") or "~/tools/tts/vieneu/bin/python").expanduser())


def settings() -> dict:
    """{ok, problem, voices: [{name, description}], default}."""
    py = python_path()
    if not Path(py).exists():
        return {"ok": False, "problem": f"Chưa thấy VieNeu ({py}). Cài VieNeu hoặc đặt TTS_PYTHON trong Cài đặt.", "voices": [], "default": ""}
    with _lock:
        if _voices_cache.get("py") != py:
            try:
                r = subprocess.run([py, str(WORKER), "voices"], capture_output=True, text=True, timeout=30)
                data = json.loads(r.stdout or "{}")
            except (OSError, ValueError, subprocess.TimeoutExpired):
                data = {}
            _voices_cache.clear()
            _voices_cache.update(py=py, voices=data.get("voices") or [], default=data.get("default") or "")
        vs, df = _voices_cache["voices"], _voices_cache["default"]
    if not vs:
        return {"ok": False, "problem": "Không đọc được danh sách giọng VieNeu.", "voices": [], "default": ""}
    want = config.get("TTS_VOICE") or "Trúc Ly"
    return {"ok": True, "problem": "", "voices": vs, "default": want if any(v["name"] == want for v in vs) else (df or vs[0]["name"])}


def _key(voice: str, text: str) -> str:
    return hashlib.sha1(f"{voice}\n{text}".encode()).hexdigest()[:12]


def load(folder: Path) -> dict:
    d = editor._read_json(folder / FILE)
    d["say"] = d["say"] if isinstance(d.get("say"), dict) else {}
    d["takes"] = d["takes"] if isinstance(d.get("takes"), dict) else {}
    d["voice"] = str(d.get("voice") or "")
    return d


def _spoken(d: dict, text: str) -> str:
    """Chữ đưa cho giọng máy đọc: bản "đọc là" nếu có (ví dụ cardigan -> các-đi-gần), không thì chính câu phụ đề."""
    say = str(d["say"].get(text) or "").strip()
    return " ".join((say or text).split())


def plan(folder: Path, d: dict | None = None, cues: list | None = None) -> dict:
    """Trạng thái từng câu + giờ đặt giọng (theo video gốc)."""
    d = d or load(folder)
    cues = editor.clean_cues(editor.load_subs(folder)["cues"] if cues is None else cues, 0.0)
    vlen = editor.probe_media(folder / editor.ORIGINAL)["duration"] or (cues[-1]["end"] + 1 if cues else 0)
    voice = d["voice"] or settings()["default"]
    rows, prev_end = [], 0.0
    for i, c in enumerate(cues):
        spoken = _spoken(d, c["text"])
        k = _key(voice, spoken)
        t = d["takes"].get(k)
        if t and not (folder / DIR / t["file"]).is_file():
            t = None
        row = {"start": c["start"], "text": c["text"], "key": k, "say": d["say"].get(c["text"], ""), "has": bool(t), "status": "none"}
        if t:
            sp = float(t.get("speed") or 1.0)
            nxt = cues[i + 1]["start"] + LEAD if i + 1 < len(cues) else vlen
            st = max(c["start"] + LEAD, prev_end + GAP)
            room = max(nxt - GAP - st, 0.1)
            tempo = sp
            if t["duration"] / sp > room:
                tempo = max(sp, min(AUTO_MAX, t["duration"] / room))
            end = st + t["duration"] / tempo
            over = end - (nxt - GAP)
            row.update(duration=t["duration"], clarity=t.get("clarity"), speed=sp, tempo=round(tempo, 3), at=round(st, 2), end=round(end, 2),
                       status="ok" if over <= 0.01 and tempo <= sp + 0.001 else ("auto" if over <= 0.01 else "over"), over=round(max(over, 0), 2))
            prev_end = end
        else:
            old = [x for x in d["takes"].values() if x.get("text_of") == c["text"] or x.get("start") == c["start"]]
            row["status"] = "stale" if old else "none"
        rows.append(row)
    sig = hashlib.sha1(json.dumps([(r["key"], r.get("tempo"), r.get("at")) for r in rows]).encode()).hexdigest()[:12]
    built = (folder / VOICE_OUT).is_file() and d.get("built_sig") == sig
    return {"voice": voice, "rows": rows, "sig": sig, "built": built, "built_at": d.get("built_at", "") if built else "",
            "has_any": any(r["has"] for r in rows), "ever_built": bool(d.get("built_at"))}


def info(folder: Path) -> dict:
    s = settings()
    out = {"ok": s["ok"], "problem": s["problem"], "voices": s["voices"], "default": s["default"]}
    if s["ok"] and (folder / FILE).exists():
        out.update(plan(folder))
    else:
        out.update(voice=s["default"], rows=[], built=False, has_any=False, ever_built=False)
    return out


def _save(folder: Path, d: dict) -> None:
    editor._write_json(folder / FILE, d)


def set_item(rel: str, text: str, say: str | None = None, speed: float | None = None, voice: str | None = None) -> dict:
    """Sửa "đọc là" / tốc độ của một câu, hoặc đổi giọng cả video. Không cần chạy lại TTS khi chỉ đổi tốc độ."""
    folder = library.resolve(rel)
    if editor._busy.locked():
        raise editor.EditError("Đang có tác vụ chỉnh sửa chạy. Đợi nó xong rồi thử lại.")
    d = load(folder)
    if voice is not None:
        if voice not in {v["name"] for v in settings()["voices"]}:
            raise editor.EditError("Không có giọng này.")
        d["voice"] = voice
    text = editor._clean_text(text or "")
    if say is not None and text:
        say = " ".join(str(say).split())[:editor.MAX_CUE_CHARS]
        if say and say != " ".join(text.split()):
            d["say"][text] = say
        else:
            d["say"].pop(text, None)
    if speed is not None and text:
        k = _key(d["voice"] or settings()["default"], _spoken(d, text))
        if k in d["takes"]:
            d["takes"][k]["speed"] = round(min(max(float(speed), SPEEDS[0]), SPEEDS[1]), 2)
    _save(folder, d)
    return plan(folder, d)


def gen_job(job, rel: str, starts: list | None = None, voice: str = "", takes: int = 3) -> str:
    """Tạo giọng cho các câu (theo giờ bắt đầu; None = mọi câu chưa có giọng). Câu được chọn lại thì luôn đọc lại."""
    if not editor._busy.acquire(blocking=False):
        raise editor.EditError("Đang có một tác vụ chỉnh sửa khác chạy. Đợi nó xong rồi thử lại.")
    try:
        s = settings()
        if not s["ok"]:
            raise editor.EditError(s["problem"])
        folder = library.resolve(rel)
        d = load(folder)
        if voice:
            if voice not in {v["name"] for v in s["voices"]}:
                raise editor.EditError("Không có giọng này.")
            d["voice"] = voice
        d["voice"] = d["voice"] or s["default"]
        cues = editor.clean_cues(editor.load_subs(folder)["cues"], 0.0)
        if not cues:
            raise editor.EditError("Chưa có phụ đề. Phiên âm / dịch trước rồi mới lồng tiếng.")
        want = None
        if starts is not None:
            want = set()
            for x in starts:
                try:
                    want.add(round(float(x), 2))
                except (TypeError, ValueError):
                    continue
        todo, seen = [], set()
        for c in cues:
            spoken = _spoken(d, c["text"])
            k = _key(d["voice"], spoken)
            t = d["takes"].get(k)
            fresh = t and (folder / DIR / t["file"]).is_file()
            if (c["start"] in want if want is not None else not fresh) and k not in seen:
                seen.add(k)
                todo.append({"id": k, "text": spoken, "out": str(folder / DIR / f"{k}.new.wav"), "src": c["text"], "start": c["start"]})
        todo = todo[:MAX_ITEMS]
        if not todo:
            return "Câu nào cũng đã có giọng. Bấm ↻ ở từng câu nếu muốn đọc lại."
        (folder / DIR).mkdir(exist_ok=True)
        t = editor.tools()
        wh = t["whisper"]
        req = {"voice": d["voice"], "takes": takes, "post_filter": POST_FILTER, "ffmpeg": t["ffmpeg"]["path"],
               "whisper_cli": wh["cli"] if wh["ok"] else "", "whisper_model": wh["model"] if wh["ok"] else "",
               "items": [{"id": x["id"], "text": x["text"], "out": x["out"]} for x in todo]}
        job.log(f"Đọc {len(todo)} câu bằng giọng {d['voice']} (mỗi câu tối đa {takes} lần, giữ bản rõ nhất)"
                + ("" if wh["ok"] else "; chưa có whisper nên không chấm độ rõ") + "...")
        job.set_progress(0, len(todo))
        proc = subprocess.Popen([python_path(), str(WORKER), "gen"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, errors="replace")
        stop = threading.Event()

        def watch():   # bấm Dừng: ngắt ngay tiến trình TTS
            while not stop.wait(0.5):
                if job.cancelled and proc.poll() is None:
                    proc.terminate()
                    return
        threading.Thread(target=watch, daemon=True).start()
        by_id = {x["id"]: x for x in todo}
        done, errors = 0, []
        try:
            proc.stdin.write(json.dumps(req, ensure_ascii=False))
            proc.stdin.close()
            for line in proc.stdout:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                x = by_id.get(r.get("id"))
                if not x:
                    continue
                done += 1
                if r.get("error"):
                    errors.append(f"{x['src'][:40]}: {r['error']}")
                    job.log(f"Lỗi: {x['src'][:60]} ({r['error'][:120]})")
                else:
                    final = folder / DIR / f"{x['id']}.wav"
                    os.replace(x["out"], final)
                    old = d["takes"].get(x["id"]) or {}
                    d["takes"][x["id"]] = {"file": final.name, "voice": d["voice"], "text": x["text"], "text_of": x["src"], "start": x["start"],
                                           "duration": r["duration"], "clarity": r.get("clarity"), "speed": old.get("speed", 1.0),
                                           "made_at": datetime.now(timezone.utc).isoformat()}
                    _save(folder, d)   # lưu từng câu: dừng giữa chừng vẫn giữ các câu đã đọc
                    cl = r.get("clarity")
                    job.log(f"{done}/{len(todo)} {x['text'][:60]}" + (f"  (rõ {cl:.2f})" if cl is not None else ""))
                job.set_progress(done, len(todo))
            proc.wait()
        finally:
            stop.set()
            for x in todo:
                Path(x["out"]).unlink(missing_ok=True)
        if job.cancelled:
            return f"Đã dừng. Giữ {done - len(errors)} câu đã đọc xong."
        if proc.returncode not in (0, None) and done < len(todo):
            err = (proc.stderr.read() or "").strip().splitlines()
            raise editor.EditError("VieNeu lỗi: " + (err[-1][:300] if err else f"mã {proc.returncode}"))
        _cleanup(folder, d, cues)
        _save(folder, d)
        ok = done - len(errors)
        low = sum(1 for x in todo if (d["takes"].get(x["id"]) or {}).get("clarity") is not None and d["takes"][x["id"]]["clarity"] < 0.8)
        msg = f"Đã đọc {ok}/{len(todo)} câu bằng giọng {d['voice']}. Nghe thử từng câu, chỉnh tốc độ, rồi bấm Ghép giọng."
        if low:
            msg += f" {low} câu đọc chưa rõ (dưới 0,8): bấm ↻ để đọc lại hoặc sửa ô Đọc là."
        if errors:
            msg += f" {len(errors)} câu lỗi."
        return msg
    finally:
        editor._busy.release()


def _cleanup(folder: Path, d: dict, cues: list) -> None:
    """Bỏ file giọng không còn câu nào dùng (đã sửa chữ / đổi giọng), giữ đúng giọng của các câu hiện tại ở mọi giọng."""
    keep = set()
    for c in cues:
        spoken = _spoken(d, c["text"])
        for v in {t.get("voice") for t in d["takes"].values()} | {d["voice"]}:
            keep.add(_key(v, spoken))
    for k in list(d["takes"]):
        if k not in keep:
            (folder / DIR / d["takes"][k]["file"]).unlink(missing_ok=True)
            del d["takes"][k]


def build_job(job, rel: str) -> str:
    """Ghép giọng các câu thành voice.wav theo giờ phụ đề (giờ video gốc), thay giọng đọc hiện có."""
    if not editor._busy.acquire(blocking=False):
        raise editor.EditError("Đang có một tác vụ chỉnh sửa khác chạy. Đợi nó xong rồi thử lại.")
    try:
        folder = library.resolve(rel)
        d = load(folder)
        p = plan(folder, d)
        rows = [r for r in p["rows"] if r["has"]]
        if not rows:
            raise editor.EditError("Chưa có câu nào có giọng. Bấm Tạo giọng trước.")
        missing = len(p["rows"]) - len(rows)
        vlen = editor.probe_media(folder / editor.ORIGINAL)["duration"]
        ff = editor.tools()["ffmpeg"]["path"]
        cmd = [ff, "-v", "error", "-y"]
        parts = []
        for i, r in enumerate(rows):
            cmd += ["-i", str(folder / DIR / d["takes"][r["key"]]["file"])]
            # atempo phải đứng TRƯỚC aresample: đặt sau thì ffmpeg làm lệch mốc giờ, cả đường giọng vào sớm (đã đo 2026-11-24)
            tf = f"atempo={r['tempo']:.3f}," if abs(r["tempo"] - 1) > 0.001 else ""
            parts.append(f"[{i}:a]{tf}aresample=48000,aformat=channel_layouts=stereo,adelay={int(r['at'] * 1000)}:all=1[v{i}]")
        fc = ";".join(parts) + ";" + "".join(f"[v{i}]" for i in range(len(rows))) + \
            f"amix=inputs={len(rows)}:normalize=0:duration=longest,apad,atrim=0:{vlen:.3f}[a]"
        tmp = folder / "voice.dub.tmp.wav"
        cmd += ["-filter_complex", fc, "-map", "[a]", "-c:a", "pcm_s16le", str(tmp)]
        job.log(f"Ghép {len(rows)} câu thành giọng đọc ({vlen:.1f} giây)...")
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
        if r.returncode != 0:
            tmp.unlink(missing_ok=True)
            raise editor.EditError("Ghép giọng lỗi: " + (r.stderr.strip().splitlines() or ["?"])[-1][:300])
        editor._remove_voice_files(folder)
        tmp.replace(folder / VOICE_OUT)
        d["built_at"], d["built_sig"] = datetime.now(timezone.utc).isoformat(), p["sig"]
        _save(folder, d)
        over = sum(1 for x in rows if x["status"] == "over")
        msg = f"Đã ghép {len(rows)} câu thành {VOICE_OUT} (bước 3 Giọng đọc). Hạ âm lượng gốc ở phần Âm thanh rồi Xuất video."
        if missing:
            msg += f" {missing} câu chưa có giọng nên bị bỏ qua."
        if over:
            msg += f" {over} câu dài hơn chỗ trống, đọc lấn sang câu sau."
        return msg
    finally:
        editor._busy.release()


def wav_path(rel: str, key: str) -> Path:
    folder = library.resolve(rel)
    t = load(folder)["takes"].get(str(key))
    if not t:
        raise ValueError("Không có giọng câu này.")
    return folder / DIR / t["file"]


def remove_all(folder: Path) -> None:
    """Xoá dữ liệu lồng tiếng (khi duyệt bản nháp)."""
    (folder / FILE).unlink(missing_ok=True)
    d = folder / DIR
    if d.is_dir():
        for f in d.iterdir():
            f.unlink(missing_ok=True)
        try:
            d.rmdir()
        except OSError:
            pass
