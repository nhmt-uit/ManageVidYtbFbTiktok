"""Nhập link affiliate riêng cho từng video từ file CSV.

CSV có hàng tiêu đề (tên cột không phân biệt hoa thường): cột nhận diện video là video, id hoặc video_id;
cột link là link, url hoặc affiliate. Cột khác (ví dụ title) bị bỏ qua. Không có hàng tiêu đề thì cột 1 là
video, cột cuối là link.

Cột video có thể là ID YouTube (11 ký tự), link YouTube, tên thư mục video, hoặc một đoạn tên đủ để nhận ra
đúng một video.
"""
from __future__ import annotations

import csv
import io
import re

from . import commenter, library

YT_URL_RE = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/)([\w-]{11})")
ID_RE = re.compile(r"^[\w-]{11}$")
VIDEO_COLS = ("video", "id", "video_id", "videoid")
LINK_COLS = ("link", "url", "affiliate", "link_affiliate")


def _rows(text: str) -> list[list[str]]:
    text = text.lstrip("\ufeff")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]


def _match(key: str, videos: list[dict]):
    """Trả về (video, lỗi). videos: [{rel, folder, yt_id, title}]."""
    k = key.strip()
    m = YT_URL_RE.search(k)
    if m:
        k = m.group(1)
    if ID_RE.match(k):
        hit = [v for v in videos if v["yt_id"] == k]
        if len(hit) == 1:
            return hit[0], ""
        if len(hit) > 1:
            return None, "ID này có ở nhiều thư mục"
    low = k.lower()
    hit = [v for v in videos if v["folder"].lower() == low or v["rel"].lower() == low]
    if not hit and len(low) >= 4:
        hit = [v for v in videos if low in v["folder"].lower() or low in v["title"].lower()]
    if len(hit) == 1:
        return hit[0], ""
    if len(hit) > 1:
        return None, f"khớp {len(hit)} video, hãy dùng ID YouTube"
    return None, "không tìm thấy video"


def import_csv(text: str) -> dict:
    rows = _rows(text)
    if not rows:
        return {"updated": 0, "problems": [{"line": 0, "key": "", "reason": "File trống."}], "total": 0}
    head = [c.lower() for c in rows[0]]
    vi = next((i for i, c in enumerate(head) if c in VIDEO_COLS), None)
    li = next((i for i, c in enumerate(head) if c in LINK_COLS), None)
    if vi is not None and li is not None:
        body, first = rows[1:], 2
    elif vi is None and li is None:
        vi, li, body, first = 0, len(rows[0]) - 1, rows, 1
        if li == 0:
            return {"updated": 0, "problems": [{"line": 1, "key": "", "reason": "Cần ít nhất 2 cột: video và link."}], "total": 0}
    else:
        return {"updated": 0, "problems": [{"line": 1, "key": "", "reason": "Thiếu cột: cần cả cột video (hoặc id) và cột link."}], "total": 0}

    videos = []
    for v in library.scan()["videos"]:
        videos.append({"rel": v["rel"], "folder": v["folder"], "yt_id": v["yt_id"], "title": v["title"]})

    updated, skipped_empty, problems = 0, 0, []
    for n, r in enumerate(body, first):
        key = r[vi] if vi < len(r) else ""
        link = r[li] if li < len(r) else ""
        if not key:
            continue
        if not link:
            skipped_empty += 1  # ô link trống: bỏ qua, không xóa link cũ
            continue
        v, why = _match(key, videos)
        if v is None:
            problems.append({"line": n, "key": key, "reason": why})
            continue
        try:
            commenter.save_link(library.resolve(v["rel"]), link)
        except ValueError as e:
            problems.append({"line": n, "key": key, "reason": str(e)})
            continue
        updated += 1
    return {"updated": updated, "skipped_empty": skipped_empty, "problems": problems, "total": len(body)}
