"""Kiểm tra video có đạt yêu cầu của Facebook Reels trước khi hẹn giờ (dùng ffprobe, đi kèm ffmpeg).

Theo tài liệu Reels Publishing API của Meta:
  - độ dài 3 đến 90 giây
  - độ phân giải tối thiểu 540x960, khuyến nghị 1080x1920
  - tỉ lệ khung hình 9:16 (nằm trong khoảng từ 16:9 đến 9:16)
  - 24 đến 60 khung hình/giây

Video ngang (rộng/cao từ LAND_RATIO trở lên) không đăng dạng Reel mà đăng dạng video thường của Page (scheduler.schedule_page_video),
nên được kiểm theo chuẩn video ngang: 3 giây đến 4 giờ, tối thiểu 640x360 (khuyến nghị 1920x1080). Kết quả có "kind": vertical | landscape.

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
LAND_RATIO = 1.2     # rộng/cao từ mức này trở lên = video ngang (đăng dạng video thường, không phải Reel)
LAND_MIN_W, LAND_MIN_H = 640, 360
LAND_REC_H = 720     # cạnh ngắn dưới mức này chỉ cảnh báo (khuyến nghị 1920x1080)
LAND_MAX_DUR = 4 * 3600.0   # video Page tối đa 240 phút
LAND_RATIO_169 = 16 / 9


def kind_of(w: int, h: int) -> str:
    """"landscape" nếu là video ngang (đăng dạng video thường), ngược lại "vertical" (đăng dạng Reel)."""
    return "landscape" if w and h and w / h >= LAND_RATIO else "vertical"


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
    kind = kind_of(w, h)
    if kind == "landscape":
        return _evaluate_landscape(w, h, dur, fps, has_audio)

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
    return {"errors": errors, "warnings": warnings, "w": w, "h": h, "duration": round(dur, 1), "fps": round(fps, 1), "has_audio": has_audio,
            "kind": kind}


def _evaluate_landscape(w: int, h: int, dur: float, fps: float, has_audio: bool) -> dict:
    """Chuẩn video ngang (đăng dạng video thường của Page, đăng tay YouTube)."""
    errors: list[str] = []
    warnings: list[str] = []
    if dur and dur < MIN_DUR:
        errors.append(f"Video chỉ dài {dur:.1f} giây, cần tối thiểu {MIN_DUR:g} giây.")
    if dur > LAND_MAX_DUR:
        errors.append(f"Video dài {dur / 60:.0f} phút, Facebook chỉ nhận video tối đa {LAND_MAX_DUR / 60:.0f} phút.")
    if not dur:
        warnings.append("Không đọc được độ dài video.")
    if w < LAND_MIN_W or h < LAND_MIN_H:
        errors.append(f"Độ phân giải {w}x{h} thấp hơn mức tối thiểu {LAND_MIN_W}x{LAND_MIN_H}.")
    elif h < LAND_REC_H:
        warnings.append(f"Độ phân giải {w}x{h} khá thấp (nên từ 1280x720, tốt nhất 1920x1080).")
    if abs(w / h - LAND_RATIO_169) > RATIO_TOL * 3:
        warnings.append(f"Khung hình {w}x{h} không phải ngang 16:9, YouTube/Facebook sẽ thêm viền đen.")
    if fps and not (MIN_FPS <= fps <= MAX_FPS):
        warnings.append(f"Tốc độ khung hình {fps:.0f} fps nằm ngoài khoảng 24 đến 60 fps.")
    if not has_audio:
        warnings.append("Video không có âm thanh.")
    return {"errors": errors, "warnings": warnings, "w": w, "h": h, "duration": round(dur, 1), "fps": round(fps, 1), "has_audio": has_audio,
            "kind": "landscape"}


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
        res = data.get("result")
        # kết quả lưu từ bản cũ (chưa có "kind") của video ngang được kiểm lại theo chuẩn video ngang
        if data.get("sig") == _sig(video) and isinstance(res, dict) and (res.get("kind") or kind_of(res.get("w", 0), res.get("h", 0)) == "vertical"):
            return res
    except (ValueError, OSError):
        pass
    return None


def summary(folder: Path) -> dict:
    """Bản tóm tắt cho giao diện: {state: ""|ok|warn|error, messages: [...]}. Chỉ đọc cache, không chạy ffprobe."""
    res = cached(folder)
    if res is None:
        return {"state": "", "messages": [], "kind": ""}
    kind = res.get("kind") or kind_of(res.get("w", 0), res.get("h", 0))
    return {"state": state_of(res), "messages": list(res.get("errors", [])) + list(res.get("warnings", [])), "kind": kind}


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
    land = 0
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
        land += res.get("kind") == "landscape"
        if st != "ok":
            job.log(f"{'KHÔNG ĐẠT' if st == 'error' else 'Lưu ý'}: {folder.name}: {' '.join(res['errors'] + res['warnings'])}")
        job.set_progress(i, len(videos))
    return (f"Đã kiểm tra {sum(counts.values())} video: {counts['ok']} đạt, {counts['warn']} cần xem lại, {counts['error']} không đạt yêu cầu."
            + (f" Trong đó {land} video ngang (kiểm theo chuẩn video ngang, hẹn giờ sẽ đăng dạng video thường chứ không phải Reel)." if land else ""))


# ---------- Chuẩn chung để đăng được cả Reels Facebook, Instagram Reels và YouTube Shorts ----------
# Lấy mức chặt nhất của từng mục: dọc 9:16, tối thiểu 540x960, 3 đến 90 giây, 24 đến 60 fps, MP4 với hình H.264 và tiếng AAC.
# (Instagram / YouTube có thể cho dài hơn, nhưng Reels Facebook qua API chỉ nhận tối đa 90 giây.)
STANDARD_NAME = "Reels Facebook, Instagram Reels và YouTube Shorts"
STRICT_RATIO_TOL = 0.02


STANDARD_NAME_LAND = "video ngang 16:9 (YouTube, video Facebook)"
LAND_STRICT_MIN_H = 720


def standard_name(kind: str) -> str:
    return STANDARD_NAME_LAND if kind == "landscape" else STANDARD_NAME


def strict_check(path: Path) -> dict:
    """Kiểm tra một file video theo chuẩn chung của đúng loại khung: dọc (Reels/Shorts) hoặc ngang 16:9 (YouTube, video Facebook).
    Trả về {errors, warnings, w, h, duration, fps, has_audio, kind}. errors rỗng = đăng được. Ném RuntimeError nếu không có ffprobe."""
    info = probe(path)
    res = evaluate(info)
    errors, warnings = list(res["errors"]), [w for w in res["warnings"] if "9:16" not in w and "16:9" not in w and "fps" not in w]
    w, h, fps = res["w"], res["h"], res["fps"]
    if res.get("kind") == "landscape":
        if abs(w / h - LAND_RATIO_169) > STRICT_RATIO_TOL:
            errors.append(f"Khung hình {w}x{h} không phải ngang 16:9.")
        if h < LAND_STRICT_MIN_H:
            errors.append(f"Độ phân giải {w}x{h} thấp hơn 1280x720.")
        warnings = [x for x in warnings if "khá thấp" not in x]
    elif w and h and abs(w / h - RATIO) > STRICT_RATIO_TOL:
        errors.append(f"Khung hình {w}x{h} không phải dọc 9:16.")
    if fps and not (MIN_FPS <= fps <= MAX_FPS):
        errors.append(f"Tốc độ khung hình {fps:.0f} fps nằm ngoài khoảng 24 đến 60 fps.")
    streams = info.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video" and (s.get("disposition") or {}).get("attached_pic") != 1), None)
    if v and v.get("codec_name") != "h264":
        errors.append(f"Hình mã hoá {v.get('codec_name') or 'không rõ'}, cần H.264.")
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if a and a.get("codec_name") != "aac":
        errors.append(f"Âm thanh mã hoá {a.get('codec_name') or 'không rõ'}, cần AAC.")
    fmt = str((info.get("format") or {}).get("format_name") or "")
    if info and "mp4" not in fmt.split(","):
        errors.append("File không phải MP4.")
    return {**res, "errors": errors, "warnings": warnings}
