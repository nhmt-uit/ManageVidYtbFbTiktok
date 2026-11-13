"""Kho video của một Page còn đủ đăng trong bao nhiêu ngày.

kho = video chưa lên lịch (bỏ video không đạt Reels); mỗi ngày đăng dùng `posts_per_day` video theo quy tắc của Page.
Lịch đã hẹn tính riêng: số ngày từ hôm nay đến bài hẹn xa nhất. Tổng hai phần là "runway" (số ngày Page còn có bài để đăng).
"""
from __future__ import annotations

from datetime import datetime

from . import commenter, config, pages, planner, publish

WARN_DAYS = 7   # dưới mức này thì nhắc nhẹ (vàng); dưới LOW_STOCK_DAYS thì báo đỏ


def low_days() -> int:
    return config.get_int("LOW_STOCK_DAYS", 3, 1, 60)


def stock_days(rules: dict, n: int, start_weekday: int, cap: int = 365) -> int:
    """Số ngày liên tiếp (tính cả ngày nghỉ nằm giữa) mà n video đăng đủ, bắt đầu từ thứ `start_weekday` (0 = Thứ Hai)."""
    per = planner.posts_per_day(rules)
    if per <= 0:
        return 0
    off = set(rules["days_off"])
    if len(off) >= 7:
        return 0
    left, day, last = n, 0, 0
    wd = start_weekday
    while day < cap:
        if wd not in off:
            if left < per:
                break
            left -= per
            last = day + 1
        day += 1
        wd = (wd + 1) % 7
    return last


def page_stock(page: dict, videos: list[dict], now: datetime | None = None) -> dict:
    rules = planner.rules_of(page)
    tz = pages.tz_of(page)
    local = (now or datetime.now().astimezone()).astimezone(tz)
    usable = bad = 0
    queue_end = None
    for v in videos:
        if not v["scheduled"]:
            if (v.get("reel_check") or {}).get("state") == "error":
                bad += 1
            else:
                usable += 1
            continue
        if v["scheduled"] == "?" or v["publish_status"] in publish.BAD or v["publish_status"] == "published":
            continue
        when = commenter._parse(v["scheduled"])
        if when is None:
            continue
        when = when.astimezone(tz)
        if when > local and (queue_end is None or when > queue_end):
            queue_end = when
    out = {"new": usable, "unusable": bad, "per_day": 0, "stock_days": None, "queue_until": "", "queue_days": 0,
           "runway_days": None, "level": "unknown", "low_days": low_days()}
    if queue_end is not None:
        out["queue_until"] = f"{queue_end:%Y-%m-%d}"
        out["queue_days"] = (queue_end.date() - local.date()).days + 1
    if not rules["slots"]:
        return out
    out["per_day"] = planner.posts_per_day(rules)
    # kho bắt đầu được dùng sau ngày cuối của lịch đã hẹn (hoặc từ hôm nay nếu chưa hẹn gì)
    start = queue_end.date() if queue_end is not None else local.date()
    first_free = start.weekday() if queue_end is None else (start.weekday() + 1) % 7
    out["stock_days"] = stock_days(rules, usable, first_free)
    out["runway_days"] = out["queue_days"] + out["stock_days"]
    lo = out["low_days"]
    out["level"] = "low" if out["runway_days"] < lo else "warn" if out["runway_days"] < max(WARN_DAYS, lo) else "ok"
    return out


def alerts(job=None) -> list[str]:
    """Gửi thông báo cho Page sắp hết video (chống lặp 20 giờ). Trả về danh sách Page đã báo."""
    from . import library, notify
    sent = []
    if not notify.configured():
        return sent
    for p in pages.all_pages():
        if not p.get("token"):
            continue
        videos = library.scan(p["id"])["videos"]
        if not videos:   # Page mới chưa có video nào thì chưa cần nhắc
            continue
        info = page_stock(p, videos)
        if info["level"] != "low":
            continue
        until = info["queue_until"][8:10] + "/" + info["queue_until"][5:7] if info["queue_until"] else "chưa hẹn bài nào"
        body = (f"Còn {info['new']} video chưa lên lịch, lịch đã hẹn đến {until}. "
                f"Page chỉ còn đủ bài cho khoảng {info['runway_days']} ngày. Vào mục Tải video để tải thêm.")
        if notify.send(f"Sắp hết video: {pages.label(p)}", body, key=f"stock:{p['id']}", ttl_hours=20):
            sent.append(p["id"])
            if job is not None:
                job.log(f"Đã báo sắp hết video: {pages.label(p)}")
    return sent
