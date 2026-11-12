"""Dò viền đen có sẵn trong video gốc (video đã bị đóng khung đen quanh hình) để cắt bỏ trước khi phóng to lên 1080x1920.

Dùng cropdetect của ffmpeg ở nhiều thời điểm rồi lấy vùng hình chung (hợp của các vùng có hình), nên một cảnh tối
đơn lẻ không làm cắt nhầm vào nội dung. Chỉ cắt khi viền đủ rõ; nếu kết quả đáng ngờ thì giữ nguyên khung.
"""
from __future__ import annotations

import re
import subprocess

SAMPLES = (0.08, 0.2, 0.32, 0.44, 0.56, 0.68, 0.8, 0.92)
LIMIT = 20            # ngưỡng độ sáng coi là đen (0..255)
MIN_EDGE_PCT = 1.2    # mỗi cạnh phải có viền ít nhất ngần này % mới đáng cắt
MIN_KEEP = 0.6        # vùng giữ lại phải còn ít nhất 60% diện tích, nhỏ hơn thì coi là đáng ngờ
_CROP = re.compile(r"crop=(\d+):(\d+):(\d+):(\d+)")


def detect(ffmpeg: str, path, duration: float, width: int, height: int, cancelled=lambda: False) -> dict | None:
    """Trả về {"x","y","w","h","left","top","right","bottom"} (pixel của video gốc) hoặc None nếu không có viền đen đáng cắt."""
    if not (width and height):
        return None
    points = [max(0.0, duration * f - 0.5) for f in SAMPLES] if duration and duration > 4 else [0.0]
    x0, y0, x1, y1 = width, height, 0, 0
    got = 0
    for t in points:
        if cancelled():
            return None
        cmd = [ffmpeg, "-nostdin", "-hide_banner", "-nostats", "-ss", f"{t:.2f}", "-t", "1.2", "-i", str(path),
               "-vf", f"cropdetect=limit={LIMIT}:round=2:reset=0", "-an", "-f", "null", "-"]
        try:
            err = subprocess.run(cmd, capture_output=True, text=True, timeout=60, errors="replace").stderr
        except (OSError, subprocess.SubprocessError):
            continue
        m = _CROP.findall(err)
        if not m:
            continue
        w, h, x, y = (int(v) for v in m[-1])
        x0, y0, x1, y1 = min(x0, x), min(y0, y), max(x1, x + w), max(y1, y + h)
        got += 1
    if got < max(1, min(3, len(points))):   # quá ít mẫu đo được: không đủ tin cậy
        return None
    x0, y0 = x0 - x0 % 2, y0 - y0 % 2
    x1, y1 = min(width, x1 + x1 % 2), min(height, y1 + y1 % 2)
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0 or w * h < MIN_KEEP * width * height:
        return None
    left, top, right, bottom = x0, y0, width - x1, height - y1
    big = lambda px, total: px * 100 / total >= MIN_EDGE_PCT
    if not (big(left, width) or big(right, width) or big(top, height) or big(bottom, height)):
        return None
    return {"x": x0, "y": y0, "w": w, "h": h, "left": left, "top": top, "right": right, "bottom": bottom}
