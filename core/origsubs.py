"""Dò và che phụ đề in cứng (sub gốc) trong video.

Sub in cứng thường là chữ trắng viền đen. Cách dò: lấy khung hình thưa (tối đa ~800 khung), với mỗi khung đánh dấu điểm ảnh
trắng nằm sát điểm ảnh đen (chính là nét chữ + viền). Dải ngang nào có nét chữ lặp đi lặp lại theo thời gian là chỗ đặt sub;
khoảng thời gian dải đó có nét chữ là lúc có sub. Viền đen của khung video (letterbox) được loại trừ.

Kết quả lưu ở origsubs.json trong thư mục video (toạ độ theo tỉ lệ 0..1 của video đang có, nên sửa tay được):
  {"found", "band": {"x","y","w","h"}, "ranges": [[bắt đầu, kết thúc], ...], "mode": "ranges"|"always", "detected_at", "frames"}
Khi xuất, vùng này được làm mờ + tối đi (chỉ trong các khoảng có sub, hoặc suốt video nếu mode = "always"), rồi phụ đề mới
đặt lên trên. Cần numpy (nằm trong requirements.txt).
"""
from __future__ import annotations

import subprocess
from datetime import datetime, timezone

FILE = "origsubs.json"
MAX_FRAMES = 800          # số khung hình tối đa lấy mẫu
ANALYZE_W = 360           # độ rộng khung hình khi phân tích
MODES = ("ranges", "always")


class DetectError(Exception):
    """Lỗi hiện cho người dùng."""


def _np():
    try:
        import numpy as np
    except ImportError as exc:   # noqa: BLE001
        raise DetectError("Thiếu thư viện numpy để dò sub gốc. Chạy: .venv/bin/pip install numpy rồi khởi động lại app (./service.sh restart).") from exc
    return np


def _dilate(np, mask, r: int):
    """Giãn vùng True ra r điểm ảnh theo cả hai chiều (cửa sổ vuông (2r+1)x(2r+1))."""
    d = mask.copy()
    for k in range(1, r + 1):
        d[:, k:] |= mask[:, :-k]
        d[:, :-k] |= mask[:, k:]
    e = d.copy()
    for k in range(1, r + 1):
        e[k:, :] |= d[:-k, :]
        e[:-k, :] |= d[k:, :]
    return e


def _bars(np, mean_profile, margin: int):
    """Vị trí các dải đen cố định ở mép khung (letterbox/pillarbox) + lề an toàn."""
    n = len(mean_profile)
    black = mean_profile < 14
    out = np.zeros(n, dtype=bool)
    i = 0
    while i < n and black[i]:
        i += 1
    if i:
        out[: min(n, i + margin)] = True
    j = n - 1
    while j >= 0 and black[j]:
        j -= 1
    if j < n - 1:
        out[max(0, j + 1 - margin):] = True
    return out


def detect(ffmpeg: str, video, duration: float, width: int, height: int, progress=None, cancelled=None) -> dict:
    """Trả về dict kết quả (xem đầu file). Không ghi file."""
    np = _np()
    if not (width and height and duration):
        raise DetectError("Không đọc được kích thước hoặc độ dài video.")
    sw = min(ANALYZE_W, width)
    sh = max(8, int(round(height * sw / width / 2)) * 2)
    fps = max(2.0, min(8.0, MAX_FRAMES / max(duration, 1.0)))
    cmd = [ffmpeg, "-nostdin", "-v", "error", "-i", str(video), "-an", "-vf", f"fps={fps:.4f},scale={sw}:{sh}:flags=area,format=gray",
           "-f", "rawvideo", "-"]
    fsize = sw * sh
    packed: list = []
    row_sum = np.zeros(sh)
    col_sum = np.zeros(sw)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError as exc:
        raise DetectError(f"Không chạy được FFmpeg: {exc}") from exc
    expected = max(1, int(duration * fps))
    try:
        while True:
            buf = proc.stdout.read(fsize)   # type: ignore[union-attr]
            if len(buf) < fsize:
                break
            if cancelled and cancelled():
                proc.kill()
                raise DetectError("Đã dừng theo yêu cầu.")
            g = np.frombuffer(buf, dtype=np.uint8).reshape(sh, sw)
            row_sum += g.mean(axis=1)
            col_sum += g.mean(axis=0)
            packed.append(np.packbits((g > 225) & _dilate(np, g < 45, 2), axis=None))
            if progress and len(packed) % 40 == 0:
                progress(min(70, int(70 * len(packed) / expected)), 100)
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
    n = len(packed)
    if n < 8:
        raise DetectError("Video quá ngắn hoặc không đọc được khung hình để dò sub.")

    bad_rows = _bars(np, row_sum / n, 5)
    bad_cols = _bars(np, col_sum / n, 5)
    good_cols = np.nonzero(~bad_cols)[0]
    if len(good_cols) < sw // 4:
        raise DetectError("Không phân tích được video này (phần hình quá nhỏ).")
    xlo, xhi = int(good_cols[0]), int(good_cols[-1])

    def frame_mask(i):
        m = np.unpackbits(packed[i], count=fsize).reshape(sh, sw).astype(bool)
        m[bad_rows, :] = False
        m[:, bad_cols] = False
        return m

    thr = max(3, int(0.012 * sw))
    hits = np.zeros(sh)
    for i in range(n):
        hits += (frame_mask(i).sum(axis=1) >= thr)
    frac = hits / n
    smooth = np.convolve(frac, np.ones(3) / 3, mode="same")
    smooth[: int(sh * 0.06)] = 0   # bỏ mép trên/dưới cùng
    smooth[int(sh * 0.97):] = 0
    ystar = int(np.argmax(smooth))
    peak = float(smooth[ystar])
    result = {"found": False, "frames": n, "fps": round(fps, 2), "detected_at": datetime.now(timezone.utc).isoformat(), "mode": "ranges",
              "band": {"x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0}, "ranges": []}
    if peak < 0.08:
        if progress:
            progress(100, 100)
        return result
    keep = max(0.08, 0.35 * peak)
    y0 = y1 = ystar
    while y0 > 0 and smooth[y0 - 1] >= keep:
        y0 -= 1
    while y1 < sh - 1 and smooth[y1 + 1] >= keep:
        y1 += 1
    pad = max(3, int(round((y1 - y0 + 1) * 0.5)))
    y0, y1 = max(0, y0 - pad), min(sh - 1, y1 + pad)

    counts = np.zeros(n)
    masks_band = []
    for i in range(n):
        mb = frame_mask(i)[y0:y1 + 1, :]
        counts[i] = mb.sum()
        masks_band.append(mb.sum(axis=0))
        if progress and i % 80 == 0:
            progress(70 + int(28 * i / n), 100)
    pos = counts[counts > 0]
    ref = float(np.percentile(pos, 75)) if len(pos) else 0.0
    active = counts >= max(0.2 * ref, 12)
    gap = max(1, int(round(0.25 * fps)))     # lấp khoảng trống ngắn giữa hai câu liền nhau
    idx = np.nonzero(active)[0]
    runs: list[list[int]] = []
    for i in idx:
        if runs and i - runs[-1][1] <= gap + 1:
            runs[-1][1] = int(i)
        else:
            runs.append([int(i), int(i)])
    min_len = max(2, int(round(0.3 * fps)))
    runs = [r for r in runs if r[1] - r[0] + 1 >= min_len]
    if not runs:
        if progress:
            progress(100, 100)
        return result
    ext = []   # đoạn chữ rộng nhất của từng khung có sub: (cột đầu, cột cuối)
    for a, b in runs:
        for i in range(a, b + 1):
            cols = np.nonzero(masks_band[i] >= 2)[0]
            if len(cols) and counts[i] >= max(0.2 * ref, 12):
                ext.append((int(cols[0]), int(cols[-1])))
    if not ext:
        ext = [(xlo, xhi)]
    ex = np.array(ext, dtype=float)
    lo, hi = float(np.percentile(ex[:, 0], 5)), float(np.percentile(ex[:, 1], 95))
    cx = float(np.median((ex[:, 0] + ex[:, 1]) / 2))
    padx = max(4.0, 0.03 * sw)
    half = max(cx - lo, hi - cx) + padx       # đối xứng quanh tâm chữ: sub thường nằm giữa khung
    x0, x1 = int(max(xlo, cx - half)), int(min(xhi, cx + half))
    half = 0.5 / fps
    ranges = [[round(max(0.0, a / fps - half - 0.05), 2), round(min(duration, (b + 1) / fps + half + 0.05), 2)] for a, b in runs]
    result.update(found=True, ranges=ranges,
                  band={"x": round(x0 / sw, 4), "y": round(y0 / sh, 4), "w": round((x1 - x0 + 1) / sw, 4), "h": round((y1 - y0 + 1) / sh, 4)})
    if progress:
        progress(100, 100)
    return result


def clean(raw) -> dict:
    """Làm sạch dữ liệu (đọc từ file hoặc do người dùng gửi lên). Luôn trả về dict đủ khoá."""
    raw = raw if isinstance(raw, dict) else {}
    out = {"found": bool(raw.get("found")), "mode": raw.get("mode") if raw.get("mode") in MODES else "ranges",
           "band": {"x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0}, "ranges": [], "detected_at": str(raw.get("detected_at") or ""),
           "frames": int(raw.get("frames") or 0) if str(raw.get("frames") or "0").isdigit() else 0}
    b = raw.get("band") if isinstance(raw.get("band"), dict) else {}
    vals = {}
    for k in ("x", "y", "w", "h"):
        try:
            vals[k] = max(0.0, min(1.0, float(b.get(k, 0))))
        except (TypeError, ValueError):
            vals[k] = 0.0
    vals["w"] = min(vals["w"], 1.0 - vals["x"])
    vals["h"] = min(vals["h"], 1.0 - vals["y"])
    if vals["w"] < 0.05 or vals["h"] < 0.01:
        out["found"] = False
    out["band"] = {k: round(v, 4) for k, v in vals.items()}
    rs = []
    for r in (raw.get("ranges") or [])[:3000]:
        try:
            a, z = float(r[0]), float(r[1])
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        if z > a >= 0:
            rs.append([round(a, 2), round(z, 2)])
    out["ranges"] = sorted(rs)
    if out["found"] and out["mode"] == "ranges" and not out["ranges"]:
        out["mode"] = "always"
    return out


def _merge(ranges: list[list[float]], pad: float = 0.12) -> list[tuple[float, float]]:
    merged: list[list[float]] = []
    for a, b in sorted(ranges):
        a, b = max(0.0, a - pad), b + pad
        if merged and a <= merged[-1][1] + 0.01:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def pixel_rect(info: dict, width: int, height: int) -> tuple[int, int, int, int]:
    """(x, y, w, h) tính bằng điểm ảnh của video, số chẵn, nằm trong khung."""
    b = info["band"]
    x, y = int(b["x"] * width) // 2 * 2, int(b["y"] * height) // 2 * 2
    w, h = max(2, int(b["w"] * width) // 2 * 2), max(2, int(b["h"] * height) // 2 * 2)
    w, h = min(w, width - x) // 2 * 2, min(h, height - y) // 2 * 2
    return x, y, max(2, w), max(2, h)


def cover_chain(info: dict, width: int, height: int, vin: str = "0:v", vout: str = "src") -> str:
    """Đoạn filter_complex: làm mờ + tối vùng sub gốc. info đã qua clean(). Đầu vào [vin], đầu ra [vout]."""
    x, y, w, h = pixel_rect(info, width, height)
    radius = max(2, min(h // 2 - 1, int(h * 0.24)))
    en = ""
    if info["mode"] == "ranges" and info["ranges"]:
        en = ":enable='" + "+".join(f"between(t,{a:.2f},{b:.2f})" for a, b in _merge(info["ranges"])) + "'"
    return (f"[{vin}]split=2[oc0][oc1];[oc1]crop={w}:{h}:{x}:{y},boxblur={radius}:3,eq=brightness=-0.38:saturation=0.8[ocb];"
            f"[oc0][ocb]overlay={x}:{y}{en}[{vout}]")
