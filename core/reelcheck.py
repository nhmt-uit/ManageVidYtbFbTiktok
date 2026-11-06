"""Kiểm tra video có đạt yêu cầu của Facebook Reels trước khi hẹn giờ (dùng ffprobe, đi kèm ffmpeg).

Theo tài liệu Reels Publishing API của Meta:
  - độ dài 3 đến 90 giây
  - độ phân giải tối thiểu 540x960, khuyến nghị 1080x1920
  - tỉ lệ khung hình 9:16 (nằm trong khoảng từ 16:9 đến 9:16)
  - 24 đến 60 khung hình/giây

Lỗi (error): Facebook sẽ từ chối hoặc không hiện như Reel, nên app bỏ qua video khi hẹn giờ.
Lưu ý (warning): vẫn đăng được nhưng chất lượng hoặc cách hiển thị có thể không như ý.
Kết quả lưu trong reels_check.json của thư mục video, gắn với kích thước và giờ sửa file nên tự làm mới khi file đổi.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .videofile import video_file

CACHE_FILE = "reels_check.json"
MIN_W, MIN_H = 540, 960
REC_W = 720          # dưới mức này chỉ cảnh báo (khuyến nghị 1080x1920)
MIN_DUR, MAX_DUR = 3.0, 90.0
RATIO = 9 / 16
RATIO_TOL = 0.06     # |w/h - 9/16| lớn hơn mức này thì cảnh báo "không phải 9:16"
MIN_FPS, MAX_FPS = 23.5, 60.5


def enabled() -> bool:
    return config.get("REELS_CHECK", "1") not in ("0", "false", "off", "no")


def ffprobe_path() -> str:
    """Tìm ffprobe trong PATH, rồi các thư mục Homebrew hay dùng (khi chạy app, PATH đôi khi thiếu /opt/homebrew/bin)."""
    extra = os.pathsep.join(["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"])
    return shutil.which("ffprobe") or shutil.which("ffprobe", path=extra) or ""


def available() -> bool:
    return bool(ffprobe_path())


def _fps(text) -> float:
    try:
        a, _, b = str(text).partition("/")
        return float(a) / float(b) if b else float(a)
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe(path: Path) -> dict:
    """Đọc thông tin video bằng ffprobe. Ném RuntimeError nếu không chạy được."""
    exe = ffprobe_path()
    if not exe:
        raise RuntimeError("Chưa cài ffprobe (đi kèm ffmpeg).")
    try:
        r = subprocess.run(
            [exe, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"Không chạy được ffprobe ({type(exc).__name__}).") from exc
    if r.returncode != 0:
        return {}
    try:
        return json.loads(r.stdout or "{}")
    except ValueError:
        return {}


def evaluate(info: dict) -> dict:
    """Thông tin ffprobe -> {errors, warnings, w, h, duration, fps, has_audio}."""
    errors: list[str] = []
    warnings: list[str] = []
    streams = info.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic") != 1), None)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    if not v:
        return {"errors": ["Không đọc được video (file hỏng hoặc không phải video)."], "warnings": [],
                "w": 0, "h": 0, "duration": 0.0, "fps": 0.0, "has_audio": has_audio}
    w, h = int(v.get("width") or 0), int(v.get("height") or 0)
    rot = 0
    try:
        rot = int(float((v.get("tags") or {}).get("rotate", 0)))
    except (TypeError, ValueError):
        pass
    for sd in v.get("side_data_list") or []:
        if "rotation" in sd:
            try:
                rot = int(float(sd["rotation"]))
            except (TypeError, ValueError):
                pass
    if abs(rot) % 180 == 90:
        w, h = h, w   # video xoay: kích thước hiển thị là ngược lại
    dur = 0.0
    for src in ((info.get("format") or {}).get("duration"), v.get("duration")):
        try:
            dur = float(src)
            break
        except (TypeError, ValueError):
            continue
    fps = _fps(v.get("avg_frame_rate")) or _fps(v.get("r_frame_rate"))

    if dur and dur < MIN_DUR:
        errors.append(f"Video chỉ dài {dur:.1f} giây, Reels cần tối thiểu {MIN_DUR:g} giây.")
    if dur > MAX_DUR:
        errors.append(f"Video dài {dur:.0f} giây, Reels chỉ nhận tối đa {MAX_DUR:g} giây.")
    if not dur:
        warnings.append("Không đọc được độ dài video.")
    if w and h:
        if min(w, h) < MIN_W or max(w, h) < MIN_H:
            errors.append(f"Độ phân giải {w}x{h} thấp hơn mức tối thiểu {MIN_W}x{MIN_H} của Reels.")
        elif min(w, h) < REC_W:
            warnings.append(f"Độ phân giải {w}x{h} khá thấp (Facebook khuyến nghị 1080x1920).")
        if abs(w / h - RATIO) > RATIO_TOL:
            warnings.append(f"Khung hình {w}x{h} không phải dọc 9:16, Facebook có thể hiện viền đen hoặc cắt bớt.")
    else:
        errors.append("Không đọc được độ phân giải video.")
    if fps and not (MIN_FPS <= fps <= MAX_FPS):
        warnings.append(f"Tốc độ khung hình {fps:.0f} fps nằm ngoài khoảng 24 đến 60 fps của Reels.")
    if not has_audio:
        warnings.append("Video không có âm thanh.")
    return {"errors": errors, "warnings": warnings, "w": w, "h": h, "duration": round(dur, 1), "fps": round(fps, 1), "has_audio": has_audio}


def _sig(video: Path) -> list:
    st = video.stat()
    return [st.st_size, int(st.st_mtime)]


def state_of(res: dict) -> str:
    return "error" if res.get("errors") else "warn" if res.get("warnings") else "ok"


def cached(folder: Path) -> dict | None:
    """Kết quả đã lưu nếu file video chưa đổi, ngược lại None."""
    video = video_file(folder)
    try:
        data = json.loads((folder / CACHE_FILE).read_text(encoding="utf-8"))
        if data.get("sig") == _sig(video) and isinstance(data.get("result"), dict):
            return data["result"]
    except (ValueError, OSError):
        pass
    return None


def summary(folder: Path) -> dict:
    """Bản tóm tắt cho giao diện: {state: ""|ok|warn|error, messages: [...]}. Chỉ đọc cache, không chạy ffprobe."""
    res = cached(folder)
    if res is None:
        return {"state": "", "messages": []}
    return {"state": state_of(res), "messages": list(res.get("errors", [])) + list(res.get("warnings", []))}


def ensure(folder: Path, force: bool = False) -> dict | None:
    """Kết quả kiểm tra của một video, chạy ffprobe nếu chưa có cache. None nếu không kiểm tra được (thiếu ffprobe, tắt kiểm tra)."""
    if not available():
        return None
    video = video_file(folder)
    if not video.exists():
        return None
    if not force:
        res = cached(folder)
        if res is not None:
            return res
    res = evaluate(probe(video))
    res["checked_at"] = datetime.now(timezone.utc).isoformat()
    try:
        tmp = folder / (CACHE_FILE + ".tmp")
        tmp.write_text(json.dumps({"sig": _sig(video), "result": res}, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(folder / CACHE_FILE)
    except OSError:
        pass
    return res


def run_check(job, page_id: str, force: bool = False) -> str:
    """Kiểm tra các video chưa lên lịch của một Page (tác vụ nền). Video đã có kết quả còn hiệu lực thì bỏ qua, trừ khi force."""
    from . import library
    if not available():
        raise RuntimeError("Chưa cài ffprobe (đi kèm ffmpeg) nên không kiểm tra được. Cài ffmpeg rồi thử lại.")
    videos = [v for v in library.scan(page_id)["videos"] if not v["scheduled"]]
    job.set_progress(0, len(videos))
    counts = {"ok": 0, "warn": 0, "error": 0}
    for i, v in enumerate(videos, 1):
        if job.cancelled:
            job.log("Đã dừng theo yêu cầu.")
            break
        folder = library.resolve(v["rel"])
        try:
            res = ensure(folder, force=force)
        except RuntimeError as exc:
            raise RuntimeError(str(exc)) from None
        if res is None:
            continue
        st = state_of(res)
        counts[st] += 1
        if st != "ok":
            job.log(f"{'KHÔNG ĐẠT' if st == 'error' else 'Lưu ý'}: {folder.name}: {' '.join(res['errors'] + res['warnings'])}")
        job.set_progress(i, len(videos))
    return f"Đã kiểm tra {sum(counts.values())} video: {counts['ok']} đạt, {counts['warn']} cần xem lại, {counts['error']} không đạt yêu cầu Reels."
