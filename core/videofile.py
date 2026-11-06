"""Chọn file video thật sự dùng để xem trước, kiểm tra Reels và đăng: bản đã chỉnh sửa nếu có, không thì video gốc."""
from __future__ import annotations

from pathlib import Path

ORIGINAL = "video.mp4"
EDITED = "video.edited.mp4"


def video_file(folder: Path) -> Path:
    """video.edited.mp4 (do bước Chỉnh sửa tạo ra) nếu có và không rỗng, ngược lại video.mp4."""
    edited = folder / EDITED
    try:
        if edited.is_file() and edited.stat().st_size > 0:
            return edited
    except OSError:
        pass
    return folder / ORIGINAL
