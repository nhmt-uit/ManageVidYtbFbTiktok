"""Tạo giọng đọc tiếng Việt bằng VieNeu cho ManageVideosTool. Chạy bằng Python của VieNeu (khác venv với tool):
  ~/tools/tts/vieneu/bin/python tools/vieneu_worker.py voices      -> in JSON [{"name", "description"}]
  ~/tools/tts/vieneu/bin/python tools/vieneu_worker.py gen < job.json
job.json: {"voice", "takes", "post_filter", "ffmpeg", "whisper_cli", "whisper_model",
           "items": [{"id", "text", "out"}]}
Mỗi câu đọc tối đa `takes` lần, lọc nhịp (post_filter), chấm độ rõ bằng whisper (so chữ nghe được với chữ cần đọc),
giữ bản rõ nhất vào `out`. In mỗi câu xong một dòng JSON {"id", "clarity", "duration"} (hoặc {"id", "error"}).
Không có whisper thì giữ bản đầu tiên (clarity = null).
"""
import difflib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _norm(s: str) -> list[str]:
    return re.sub(r"[^\w ]+", " ", (s or "").lower()).split()


def voices() -> None:
    spec = importlib.util.find_spec("vieneu")   # không import gói (nạp model rất lâu), chỉ đọc file giọng
    path = Path(spec.origin).parent / "assets" / "voices_v3_turbo.json" if spec and spec.origin else None
    data = json.loads(path.read_text(encoding="utf-8")) if path and path.exists() else {}
    out = [{"name": k, "description": (v or {}).get("description", "")} for k, v in (data.get("presets") or {}).items()]
    print(json.dumps({"default": data.get("default_voice") or "", "voices": out}, ensure_ascii=False))


def _duration(ffmpeg: str, wav: str) -> float:
    probe = str(Path(ffmpeg).with_name("ffprobe"))
    exe = probe if Path(probe).exists() else (shutil.which("ffprobe") or "ffprobe")
    r = subprocess.run([exe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", wav], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def _heard(job: dict, wav: str) -> str:
    fd, tmp = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:   # đệm im lặng hai đầu: whisper hay bỏ sót chữ đầu/cuối khi câu quá sát mép
        subprocess.run([job["ffmpeg"], "-v", "error", "-y", "-i", wav, "-af", "adelay=500:all=1,apad=pad_dur=0.5",
                        "-ar", "16000", "-ac", "1", tmp], check=True)
        r = subprocess.run([job["whisper_cli"], "-m", job["whisper_model"], "-l", "vi", "-nt", "-np", "-f", tmp],
                           capture_output=True, text=True, timeout=120)
        return " ".join(r.stdout.split())
    finally:
        os.remove(tmp)


def gen() -> None:
    job = json.load(sys.stdin)
    from vieneu import Vieneu   # nạp model một lần cho cả lượt
    tts = Vieneu()
    takes = max(1, min(int(job.get("takes") or 3), 6))
    can_score = bool(job.get("whisper_cli") and job.get("whisper_model"))
    for it in job["items"]:
        out = it["out"]
        work = tempfile.mkdtemp(prefix="tts_", dir=str(Path(out).parent))
        try:
            best = None
            for n in range(takes):
                raw, fast = os.path.join(work, f"raw{n}.wav"), os.path.join(work, f"t{n}.wav")
                tts.save(tts.infer(it["text"], voice=job["voice"]), raw)
                subprocess.run([job["ffmpeg"], "-v", "error", "-y", "-i", raw, "-af", job["post_filter"], fast], check=True)
                if not can_score:
                    best = (None, fast)
                    break
                r = difflib.SequenceMatcher(None, _norm(it["text"]), _norm(_heard(job, fast))).ratio()
                if best is None or r > best[0]:
                    best = (r, fast)
                if r >= 0.97:
                    break
            os.replace(best[1], out)
            print(json.dumps({"id": it["id"], "clarity": None if best[0] is None else round(best[0], 2),
                              "duration": round(_duration(job["ffmpeg"], out), 3)}, ensure_ascii=False), flush=True)
        except Exception as exc:   # noqa: BLE001  một câu lỗi không làm hỏng cả lượt
            print(json.dumps({"id": it["id"], "error": str(exc)[:300]}, ensure_ascii=False), flush=True)
        finally:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    {"voices": voices, "gen": gen}[sys.argv[1]]()
