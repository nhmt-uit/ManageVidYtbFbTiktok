"""Lên kế hoạch giờ đăng theo quy tắc của từng Fanpage.

Quy tắc của Page (lưu trong pages.json, mục "schedule"):
  slots        danh sách khung giờ trong ngày, ví dụ ["12:00", "19:00", "21:00"]
  max_per_day  số bài tối đa mỗi ngày
  days_off     các ngày không đăng (0 = thứ Hai ... 6 = Chủ nhật)

Chế độ "tự xếp": lần lượt điền video vào các khung giờ còn trống, bỏ qua ngày nghỉ, khung giờ đã có bài
của Page này, khung giờ đã qua và khung giờ vượt giới hạn 29 ngày của Facebook.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import commenter, pages, publish

SLOT_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
MAX_DAYS = 29            # Facebook chỉ cho hẹn giờ trong vòng 29 ngày
LEAD_MINUTES = 16        # tối thiểu cách hiện tại (Facebook yêu cầu hơn 10 phút)
OCCUPIED_MINUTES = 30    # đã có bài của Page trong khoảng này quanh khung giờ thì coi là khung đó đã có người
WARN_GAP_MINUTES = 60    # hai bài của cùng Page gần nhau hơn mức này thì cảnh báo
DEFAULT_MAX_PER_DAY = 5
DAY_NAMES = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ nhật"]


class PlanError(ValueError):
    pass


def parse_slots(value) -> list[str]:
    """Chuỗi "12:00, 19:30" hoặc danh sách -> danh sách "HH:MM" đã chuẩn hóa, không trùng, tăng dần."""
    if isinstance(value, str):
        parts = [p for p in re.split(r"[,\s;]+", value.strip()) if p]
    elif isinstance(value, list):
        parts = [str(p).strip() for p in value if str(p).strip()]
    else:
        raise ValueError("Khung giờ không hợp lệ.")
    out = []
    for p in parts:
        m = SLOT_RE.match(p)
        if not m:
            raise ValueError(f'Khung giờ "{p}" không hợp lệ. Dùng dạng 19:00, ngăn cách bằng dấu phẩy.')
        t = f"{int(m.group(1)):02d}:{m.group(2)}"
        if t not in out:
            out.append(t)
    if len(out) > 12:
        raise ValueError("Tối đa 12 khung giờ mỗi ngày.")
    return sorted(out)


def clean_rules(d) -> dict:
    d = d if isinstance(d, dict) else {}
    slots = parse_slots(d.get("slots", []))
    try:
        mpd = int(d.get("max_per_day", DEFAULT_MAX_PER_DAY))
    except (TypeError, ValueError):
        raise ValueError("Số bài tối đa mỗi ngày không hợp lệ.") from None
    if not 1 <= mpd <= 24:
        raise ValueError("Số bài tối đa mỗi ngày phải từ 1 đến 24.")
    off = d.get("days_off", [])
    if not isinstance(off, list):
        raise ValueError("Ngày nghỉ không hợp lệ.")
    try:
        days_off = sorted({int(x) for x in off})
    except (TypeError, ValueError):
        raise ValueError("Ngày nghỉ không hợp lệ.") from None
    if any(x < 0 or x > 6 for x in days_off):
        raise ValueError("Ngày nghỉ không hợp lệ.")
    if len(days_off) >= 7:
        raise ValueError("Không thể nghỉ cả 7 ngày trong tuần.")
    return {"slots": slots, "max_per_day": mpd, "days_off": days_off}


def rules_of(page: dict) -> dict:
    try:
        return clean_rules(page.get("schedule") or {})
    except ValueError:
        return clean_rules({})


def existing_times(page_id: str, tz: ZoneInfo, since: datetime | None = None) -> list[datetime]:
    """Giờ của các bài đã hẹn trên Page này (bỏ qua bài lỗi vì khung giờ của chúng thực ra đang trống)."""
    out = []
    for folder in commenter.find_scheduled():
        sched = commenter.read_sched(folder)
        pg = pages.resolve(sched)
        if not pg or pg["id"] != page_id or sched.get("publish_status") in publish.BAD:
            continue
        when = commenter._parse(sched.get("scheduled_for"))
        if when is None:
            continue
        when = when.astimezone(tz)
        if since is None or when >= since:
            out.append(when)
    return sorted(out)


def plan(rules: dict, n: int, earliest: datetime, tz: ZoneInfo, existing: list[datetime], now: datetime | None = None,
         partial: bool = False) -> list[datetime]:
    """Trả về n giờ đăng. Không đủ chỗ trong 29 ngày thì ném PlanError; với partial=True trả về số giờ xếp được
    (ít hơn n), và chỉ ném lỗi khi không còn chỗ nào."""
    if not rules["slots"]:
        raise PlanError("Page này chưa có khung giờ đăng. Vào tab Cài đặt Page > Quy tắc đăng để thêm, hoặc chọn kiểu hẹn cách nhau cố định.")
    now = now or datetime.now(tz)
    start_at = max(earliest, now + timedelta(minutes=LEAD_MINUTES))
    limit = now + timedelta(days=MAX_DAYS) - timedelta(hours=1)
    per_day: dict = {}
    for e in existing:
        per_day[e.date()] = per_day.get(e.date(), 0) + 1
    taken = list(existing)
    chosen: list[datetime] = []
    day = start_at.date()
    while len(chosen) < n and datetime.combine(day, datetime.min.time(), tz) <= limit:
        if day.weekday() not in rules["days_off"]:
            for slot in rules["slots"]:
                if len(chosen) >= n or per_day.get(day, 0) >= rules["max_per_day"]:
                    break
                h, m = map(int, slot.split(":"))
                dt = datetime(day.year, day.month, day.day, h, m, tzinfo=tz)
                if dt < start_at or dt > limit:
                    continue
                if any(abs((dt - t).total_seconds()) < OCCUPIED_MINUTES * 60 for t in taken):
                    continue
                chosen.append(dt)
                taken.append(dt)
                per_day[day] = per_day.get(day, 0) + 1
        day += timedelta(days=1)
    if partial and chosen:
        return chosen
    if len(chosen) < n:
        raise PlanError(
            f"Chỉ xếp được {len(chosen)}/{n} video vào khung giờ còn trống trong {MAX_DAYS} ngày tới "
            f"(khung giờ: {', '.join(rules['slots'])}; tối đa {rules['max_per_day']} bài/ngày). "
            "Bạn có thể: tick \"Nếu không đủ chỗ, chỉ xếp phần vừa đủ\" để đăng phần xếp được và để phần còn lại lần sau; "
            "chọn ít video hơn; thêm khung giờ; hoặc tăng số bài tối đa mỗi ngày."
        )
    return chosen


def warnings(page: dict, times: list[datetime], existing: list[datetime]) -> list[str]:
    """Cảnh báo (không chặn): đăng quá dày, hai bài quá gần nhau, kho comment quá ít."""
    out: list[str] = []
    if not times:
        return out
    rules = rules_of(page)
    count: dict = {}
    for t in list(existing) + list(times):
        count[t.date()] = count.get(t.date(), 0) + 1
    for d in sorted({t.date() for t in times}):
        if count[d] > rules["max_per_day"]:
            out.append(f"Ngày {d:%d/%m} có {count[d]} bài, vượt giới hạn {rules['max_per_day']} bài/ngày của Page.")
    new = set(times)
    allt = sorted(list(existing) + list(times))
    close = []
    for a, b in zip(allt, allt[1:]):
        if (a in new or b in new) and (b - a).total_seconds() < WARN_GAP_MINUTES * 60:
            close.append(f"{a:%d/%m %H:%M} và {b:%d/%m %H:%M}")
    if close:
        shown = "; ".join(close[:3]) + (f"; ... (+{len(close) - 3})" if len(close) > 3 else "")
        out.append(f"{len(close)} cặp bài cách nhau dưới {WARN_GAP_MINUTES} phút: {shown}. Đăng dày dễ bị Facebook giảm phân phối.")
    if page.get("auto_comment") and len(times) >= 5:
        pool = len(pages.read_pool(page["id"]))
        if pool < 3:
            out.append(f"Kho comment của Page chỉ có {pool} câu cho {len(times)} bài: comment sẽ lặp lại nhiều, dễ bị coi là spam.")
    return out



def posts_per_day(rules: dict) -> int:
    """Số bài Page đăng trong một ngày đăng: số khung giờ, nhưng không vượt số bài tối đa mỗi ngày."""
    return min(len(rules["slots"]), rules["max_per_day"])


def videos_needed(rules: dict, days: int) -> int:
    """Số video để đăng đủ `days` ngày liên tiếp theo quy tắc của Page (trừ các ngày nghỉ trong tuần)."""
    full_weeks, extra = divmod(days, 7)
    active_per_week = 7 - len(rules["days_off"])
    active = full_weeks * active_per_week
    if extra:   # phần dư (giao diện chỉ dùng 7/14/28 ngày nên không xảy ra): ước tính tối thiểu, coi mọi ngày nghỉ nằm trong phần dư
        active += max(0, extra - len(rules["days_off"]))
    return active * posts_per_day(rules)
