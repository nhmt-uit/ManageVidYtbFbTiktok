"""Tên file của bước Chỉnh sửa video.

video.mp4          video đang dùng (xem trước, kiểm tra Reels, hẹn giờ đăng)
video.draft.mp4    bản nháp do "Xuất video" tạo ra; chưa ảnh hưởng gì cho tới khi bấm Duyệt
edit_approved.json dấu cho biết video.mp4 là bản đã chỉnh sửa và được duyệt
"""
from __future__ import annotations

from pathlib import Path

ORIGINAL = "video.mp4"
DRAFT = "video.draft.mp4"
APPROVED = "edit_approved.json"


def video_file(folder: Path) -> Path:
    """File video thật sự dùng để xem trước, kiểm tra Reels và đăng."""
    return folder / ORIGINAL
