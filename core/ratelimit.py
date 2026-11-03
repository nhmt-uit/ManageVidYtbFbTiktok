"""Nhận biết khi Facebook giới hạn tần suất hoặc chặn tạm thời hành động của Page.

Facebook không công bố mã lỗi và thời gian chặn cụ thể cho trường hợp "giới hạn tần suất vì spam",
nên app nhận biết bằng cả mã lỗi lẫn nội dung thông báo (tiếng Anh và tiếng Việt).
"""
from __future__ import annotations

import re

PAGE_BLOCK_CODES = {32, 368}      # Page bị giới hạn / hành động bị chặn tạm thời
CALL_LIMIT_CODES = {4, 17, 613} | set(range(80000, 80015))   # giới hạn số lượt gọi API (4, 17, 613: cả app; 800xx: theo Page/sản phẩm); thường tự hết sau khoảng một giờ
SPAM_RE = re.compile(
    r"limit how often|giới hạn tần suất|temporarily blocked|bị chặn tạm thời|tạm thời bị chặn|"
    r"protect our community from spam|khỏi spam|too many (calls|requests)",
    re.IGNORECASE,
)
LONG_HOURS = 24    # Page bị chặn vì spam: các hướng dẫn thường khuyên đợi 1-2 ngày
SHORT_HOURS = 1    # giới hạn số lượt gọi API


def block_hours(code, subcode=None, message="") -> int:
    """Số giờ nên tạm dừng nếu lỗi này là giới hạn tần suất, 0 nếu không phải."""
    try:
        code = int(code)
    except (TypeError, ValueError):
        code = None
    if code in CALL_LIMIT_CODES:
        return SHORT_HOURS
    if code in PAGE_BLOCK_CODES or SPAM_RE.search(str(message or "")):
        return LONG_HOURS
    return 0
