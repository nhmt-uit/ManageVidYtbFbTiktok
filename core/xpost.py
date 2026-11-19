"""Đăng đa nền tảng: theo dõi YouTube Shorts / TikTok cho video của Page đã bật (đăng tay, app chỉ ghi trạng thái).

Page bật nền tảng nào ở Cài đặt Page (pages.platforms_of). Trạng thái từng video lưu ở xpost.json trong thư mục video:
{"youtube": {"status": "scheduled", "url": "", "at": "<iso>"}, "tiktok": {...}}. Không có = "todo" (chưa đăng).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from . import pages

FILE = "xpost.json"
PLATFORMS = ("youtube", "tiktok")
LABELS = {"youtube": "YouTube Shorts", "tiktok": "TikTok"}
STATUSES = ("todo", "scheduled", "posted")
URL_MAX = 300
YT_TITLE_MAX = 100
REMIND_AFTER_DAYS = 2   # FB đã đăng quá số ngày này mà YT/TT chưa đăng thì nhắc


def read(folder: Path) -> dict:
    """{nền tảng: {"status", "url", "at"}} cho mọi nền tảng (thiếu = todo)."""
    try:
        raw = json.loads((folder / FILE).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raw = {}
    except (OSError, ValueError):
        raw = {}
    out = {}
    for p in PLATFORMS:
        r = raw.get(p) if isinstance(raw.get(p), dict) else {}
        st = r.get("status") if r.get("status") in STATUSES else "todo"
        out[p] = {"status": st, "url": str(r.get("url") or "")[:URL_MAX], "at": str(r.get("at") or "")}
    return out


def clean_url(url) -> str:
    url = str(url or "").strip()
    if not url:
        return ""
    if len(url) > URL_MAX or not re.match(r"^https://([a-z0-9-]+\.)*(youtube\.com|youtu\.be|tiktok\.com)/\S*$", url, re.I):
        raise ValueError("Link phải là link https của YouTube hoặc TikTok.")
    return url


def write(folder: Path, platform: str, status: str, url=None) -> dict:
    if platform not in PLATFORMS:
        raise ValueError("Nền tảng không hợp lệ.")
    if status not in STATUSES:
        raise ValueError("Trạng thái không hợp lệ.")
    cur = read(folder)
    entry = cur[platform]
    if url is not None:
        entry["url"] = clean_url(url)
    if status != entry["status"]:
        entry["at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    entry["status"] = status
    if status == "todo":
        entry["url"] = ""
    data = {p: v for p, v in cur.items() if v["status"] != "todo" or v["url"]}
    path = folder / FILE
    if data:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)
    elif path.exists():
        path.unlink()
    return cur


def _sched(folder: Path) -> dict:
    try:
        d = json.loads((folder / "scheduled.json").read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def required(folder: Path, sched: dict | None = None) -> list[str]:
    """Nền tảng phải đăng thêm cho video này: theo Page đã hẹn video (chưa hẹn thì không bắt buộc gì)."""
    sched = _sched(folder) if sched is None else sched
    if not sched:
        return []
    p = pages.resolve(sched)
    return pages.platforms_of(p) if p else []


def missing(folder: Path, sched: dict | None = None) -> list[str]:
    """Nền tảng bắt buộc mà video chưa "đã đăng"."""
    st = read(folder)
    return [p for p in required(folder, sched) if st[p]["status"] != "posted"]


def blocked_reason(folder: Path) -> str:
    """Không xoá video khi Page bật đa nền tảng mà video chưa đăng đủ (xoá thì mất file để đăng tay)."""
    miss = missing(folder)
    if not miss:
        return ""
    return "Video chưa đánh dấu đã đăng " + ", ".join(LABELS[p] for p in miss) + ": đăng xong rồi đánh dấu ở mục Video trước khi xoá."


# ---------- Nội dung để copy ----------
def texts(folder: Path) -> dict:
    """Tiêu đề (dòng đầu của nội dung đăng, bỏ hashtag), hashtag và cả nội dung."""
    from . import library
    caption = library.build_caption(folder)
    tags = list(dict.fromkeys(library.HASHTAG_RE.findall(caption)))
    if not tags:
        tags = [t.strip() for t in library._read(folder / "hashtags.txt").splitlines() if t.strip().startswith("#")]
    title = ""
    for line in caption.splitlines():
        t = re.sub(r"\s+", " ", library.HASHTAG_RE.sub("", line)).strip()
        if t:
            title = t
            break
    if not title:
        title = library._read(folder / "title.txt")
    return {"title": title, "title_len": len(title), "title_max": YT_TITLE_MAX, "hashtags": " ".join(tags), "caption": caption}


# ---------- Nhắc khi còn thiếu ----------
def overdue_missing(now: datetime | None = None) -> dict:
    """{page_id: [rel...]}: video FB đã đăng quá REMIND_AFTER_DAYS ngày mà còn thiếu YT/TT."""
    from . import config
    from .commenter import _parse
    now = now or datetime.now().astimezone()
    root = config.output_dir()
    out: dict[str, list[str]] = {}
    if not root.exists():
        return out
    from . import library
    for sj in library.video_glob("scheduled.json"):
        folder = sj.parent
        sched = _sched(folder)
        if sched.get("publish_status") != "published":
            continue
        when = _parse(sched.get("scheduled_for") or "")
        if when is None or when > now - timedelta(days=REMIND_AFTER_DAYS):
            continue
        if missing(folder, sched):
            p = pages.resolve(sched)
            out.setdefault(p["id"] if p else "", []).append(folder.relative_to(root).as_posix())
    return out


def alerts(job=None) -> None:
    from . import notify
    for pid, rels in overdue_missing().items():
        p = pages.get(pid)
        name = pages.label(p) if p else "Page"
        msg = f"{len(rels)} video đã lên Facebook hơn {REMIND_AFTER_DAYS} ngày nhưng chưa đánh dấu đã đăng YouTube/TikTok. Mở mục Video, lọc \"Thiếu YT/TT\"."
        if job:
            job.log(f"Đa nền tảng ({name}): {msg}")
        notify.send(f"Còn thiếu YouTube/TikTok: {name}", msg, key=f"xpost:{pid}", ttl_hours=24)
