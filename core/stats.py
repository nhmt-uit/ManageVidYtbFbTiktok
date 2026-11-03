"""Thống kê bài đăng của một Page, để cân nhắc trước khi hẹn giờ thêm nhiều bài.

Chỉ đọc dữ liệu có sẵn trong app (scheduled.json, scheduled.old.json, trạng thái comment): KHÔNG gọi Facebook, nên không tốn
lượt gọi. Trạng thái đăng là kết quả của lần "Kiểm tra trạng thái" / kiểm tra định kỳ gần nhất; bài đã tới giờ mà chưa được
xác nhận thì tách riêng thành "chưa xác nhận" thay vì đoán là đã đăng hay lỗi. Không có lượt xem/like: các số đó cần
quyền Insights của Facebook, app chưa lấy.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone

from . import commenter, config, fbgate, library, pages, planner, publish, scheduler, stock

DAYS_BACK = 14      # số ngày hiện ở biểu đồ "đã đăng"
DAYS_AHEAD = 14     # số ngày hiện ở biểu đồ "sắp đăng"
RECENT = 10         # số bài đã đăng gần nhất
CANCEL_DAYS = 30    # tính số bài huỷ lịch trong từng ấy ngày qua

CANCEL_LABELS = {
    "fb_deleted": "Đã xóa trên Facebook",
    "fb_gone": "Facebook báo không còn bài",
    "local_only": "Chỉ gỡ trong app",
    "rebook": "Hẹn lại (bài lỗi hoặc không thấy)",
}


def _day_row(day, n: int, per_day: int, off: set) -> dict:
    return {"date": f"{day:%Y-%m-%d}", "weekday": day.weekday(), "n": n, "off": day.weekday() in off,
            "target": 0 if day.weekday() in off else per_day}


def _group(v: dict) -> str:
    """new | pending | published | error | missing | overdue"""
    if not v["scheduled"]:
        return "new"
    st = v["publish_status"]
    if st == "published":
        return "published"
    if st in publish.BAD:
        return st
    return "overdue" if v["overdue"] else "pending"


def _cancelled(vids: list[dict], now: datetime) -> dict:
    """Số bài đã huỷ lịch / gỡ lịch trong CANCEL_DAYS ngày qua, theo lý do (đọc scheduled.old.json của từng video)."""
    root = config.output_dir()
    cutoff = now.astimezone(timezone.utc) - timedelta(days=CANCEL_DAYS)
    reasons: Counter = Counter()
    total = 0
    for v in vids:
        f = root / v["rel"] / "scheduled.old.json"
        try:
            old = json.loads(f.read_text(encoding="utf-8"))
            if not isinstance(old, dict):
                continue
            when = commenter._parse(old.get("cancelled_at")) or datetime.fromtimestamp(f.stat().st_mtime, timezone.utc)
        except (OSError, ValueError, OverflowError):
            continue
        total += 1
        if when >= cutoff:
            why = old.get("cancel_reason")
            reasons[why if isinstance(why, str) and why else "rebook"] += 1
    return {"days": CANCEL_DAYS, "total_ever": total, "recent": sum(reasons.values()),
            "reasons": [{"key": k, "label": CANCEL_LABELS.get(k, k), "n": n} for k, n in reasons.most_common()]}


def page_stats(page: dict, now: datetime | None = None) -> dict:
    tz = pages.tz_of(page)
    now = (now or datetime.now().astimezone()).astimezone(tz)
    today = now.date()
    rules = planner.rules_of(page)
    off = set(rules["days_off"])
    per_day = planner.posts_per_day(rules) if rules["slots"] else 0
    vids = library.scan(page["id"])["videos"]

    counts: Counter = Counter()
    published_on: Counter = Counter()   # ngày -> số bài đã đăng (theo ngày hẹn, múi giờ Page)
    queued_on: Counter = Counter()      # ngày -> số bài đang chờ đăng
    comments: Counter = Counter()
    channels: dict = {}
    recent: list = []
    unconfirmed = 0
    for v in vids:
        g = _group(v)
        counts[g] += 1
        ch = channels.setdefault(v["channel"] or "(thư mục gốc)", Counter())
        ch["total"] += 1
        ch["published" if g == "published" else "new" if g == "new" else "pending" if g == "pending" else "problem"] += 1
        if g == "new":
            continue
        when = commenter._parse(v["scheduled"]) if v["scheduled"] != "?" else None
        when = when.astimezone(tz) if when else None
        if g in ("pending", "overdue") and when and when <= now:
            unconfirmed += 1   # đã tới giờ nhưng Facebook chưa xác nhận đã đăng
        if g == "published":
            comments[v["comment_status"] or "none"] += 1
            if when:
                published_on[when.date()] += 1
                recent.append((when, v))
        elif g == "pending" and when and when > now:
            queued_on[when.date()] += 1
    recent.sort(key=lambda x: x[0], reverse=True)

    back = [_day_row(today - timedelta(days=i), published_on[today - timedelta(days=i)], per_day, off) for i in range(DAYS_BACK - 1, -1, -1)]
    ahead = [_day_row(today + timedelta(days=i), queued_on[today + timedelta(days=i)], per_day, off) for i in range(DAYS_AHEAD)]
    last7 = sum(n for d, n in published_on.items() if today - timedelta(days=6) <= d <= today)
    last30 = sum(n for d, n in published_on.items() if today - timedelta(days=29) <= d <= today)

    judged = counts["published"] + counts["error"] + counts["missing"] + unconfirmed
    problems = {"error": counts["error"], "missing": counts["missing"], "unconfirmed": unconfirmed}

    done, waiting, failed = comments["done"], comments["pending"] + comments["retry"], comments["error"]
    wanted = sum(comments.values()) - comments["none"] - comments["skipped"]
    eff = pages.effective(page)
    cap = eff["publish_limit_24h"]
    used = len(scheduler.recent_created(page["id"]))
    gate = fbgate.gate.status()
    per = fbgate.COSTS["schedule"]
    can_gate = 0 if gate["paused_minutes"] else fbgate.affordable("user") // per
    can_cap = max(0, cap - used) if cap else None
    can_now = can_gate if can_cap is None else min(can_gate, can_cap)

    st = stock.page_stock(page, vids, now)
    return {
        "page_id": page["id"], "tz": str(tz), "today": f"{today:%Y-%m-%d}",
        "per_day": per_day, "slots": rules["slots"],
        "counts": {"total": len(vids), "new": counts["new"], "pending": counts["pending"], "published": counts["published"],
                   "problem": counts["error"] + counts["missing"] + counts["overdue"]},
        "problems": problems,
        "published": {"total": counts["published"], "last7": last7, "last30": last30, "avg_per_day7": round(last7 / 7, 1),
                      "success_rate": round(100 * counts["published"] / judged) if judged else None, "judged": judged},
        "back": back, "ahead": ahead,
        "queue": {"pending": counts["pending"], "next7": sum(r["n"] for r in ahead[:7]), "next14": sum(r["n"] for r in ahead),
                  "until": st["queue_until"], "runway_days": st["runway_days"], "stock_days": st["stock_days"],
                  "new": st["new"], "unusable": st["unusable"], "level": st["level"], "low_days": st["low_days"]},
        "comments": {"enabled": bool(page.get("auto_comment")), "done": done, "waiting": waiting, "failed": failed,
                     "expired": comments["expired"], "skipped": comments["skipped"], "none": comments["none"],
                     "wanted": wanted, "rate": round(100 * done / wanted) if wanted else None},
        "budget": {"cap": cap, "used_24h": used, "cap_left": can_cap, "fb_used": gate["used"], "fb_budget": gate["budget"],
                   "fb_paused_minutes": gate["paused_minutes"], "per_video": per, "can_schedule_now": can_now,
                   "next_free_minutes": gate["next_free_minutes"]},
        "cancelled": _cancelled(vids, now),
        "channels": [{"name": k, "total": c["total"], "new": c["new"], "pending": c["pending"], "published": c["published"], "problem": c["problem"]}
                     for k, c in sorted(channels.items())],
        "recent": [{"rel": v["rel"], "title": v["title"], "when": w.isoformat(), "permalink": v["permalink"], "comment_status": v["comment_status"]}
                   for w, v in recent[:RECENT]],
    }
