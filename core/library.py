"""Quét thư mục video, đọc/sửa nội dung bài đăng."""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import commenter, config, pages, publish, reelcheck

DATE_RE = re.compile(r"^(\d{8}) - ")
TAG_BODY = r"[\ẁ-ͯ]+"   # chữ + dấu rời (tiếng Việt gõ kiểu NFD: "a" + dấu) để không cắt hashtag giữa chữ
HASHTAG_RE = re.compile(r"#" + TAG_BODY, re.UNICODE)
MAX_CAPTION = 2000


YT_ID_RE = re.compile(r"\[([\w-]{11})\]\s*$")


OWNER_FILE = "channel.json"   # nằm trong thư mục kênh, ghi Page sở hữu thư mục: {"page_id": "..."}


def owner_of(channel_dir) -> str:
    """Page sở hữu một thư mục kênh ("" nếu chưa gán)."""
    if channel_dir is None:
        return ""
    try:
        d = json.loads((Path(channel_dir) / OWNER_FILE).read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return ""
    return str(d.get("page_id") or "") if isinstance(d, dict) else ""


def set_owner(channel_dir, page_id: str) -> None:
    (Path(channel_dir) / OWNER_FILE).write_text(
        json.dumps({"page_id": page_id}, ensure_ascii=False, indent=2), encoding="utf-8")


def yt_id(folder: Path) -> str:
    """ID YouTube của video: lấy từ meta.json, hoặc từ đuôi [id] trong tên thư mục."""
    try:
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        if isinstance(meta, dict) and meta.get("id"):
            return str(meta["id"])
    except (ValueError, OSError):
        pass
    m = YT_ID_RE.search(folder.name)
    return m.group(1) if m else ""


def iter_video_dirs():
    """Mọi thư mục chứa video.mp4 trong thư mục gốc (cả video nằm thẳng ở gốc lẫn trong thư mục kênh)."""
    root = config.output_dir()
    if not root.exists():
        return
    for p in sorted(root.iterdir()):
        if not p.is_dir():
            continue
        if (p / "video.mp4").exists():
            yield p
            continue
        for v in sorted(p.iterdir()):
            if v.is_dir() and (v / "video.mp4").exists():
                yield v


def id_index() -> dict:
    """{ID YouTube: [thư mục video, ...]} của mọi video đang có."""
    idx: dict = {}
    for d in iter_video_dirs():
        vid = yt_id(d)
        if vid:
            idx.setdefault(vid, []).append(d)
    return idx


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


TAG_RUN_RE = re.compile(r"(?<!\S)(?:#" + TAG_BODY + r")+", re.UNICODE)  # hashtag đứng đầu từ (không đụng "C#" hay #phần trong đường link), kể cả dính liền "#a#b"
DEFAULT_MAX_HASHTAGS = 5


def max_hashtags() -> int:
    """Số hashtag tối đa trong caption tự dựng (MAX_HASHTAGS trong .env, 0 = không giới hạn)."""
    return config.get_int("MAX_HASHTAGS", DEFAULT_MAX_HASHTAGS, 0, 30)


def limit_hashtags(text: str, limit: int | None = None) -> str:
    """Giữ tối đa `limit` hashtag đầu tiên của nội dung, bỏ thẻ trùng (không phân biệt hoa thường) và phần thừa.

    Thẻ bị bỏ mà phía sau còn chữ cùng dòng (hashtag nằm giữa câu) thì chỉ bỏ dấu # để câu không mất chữ.
    Nội dung không có gì phải bỏ thì trả về nguyên văn."""
    limit = max_hashtags() if limit is None else limit
    if limit <= 0 or not text:
        return text
    seen: set[str] = set()
    changed = False

    def run(m: re.Match) -> str:
        nonlocal changed
        keep, drop = [], []
        for tag in HASHTAG_RE.findall(m.group(0)):
            key = tag.lower()
            if key not in seen and len(seen) < limit:
                seen.add(key)
                keep.append(tag)
            else:
                drop.append(tag)
        if not drop:
            return m.group(0)
        changed = True
        eol = m.string.find("\n", m.end())
        rest = m.string[m.end(): len(m.string) if eol < 0 else eol]
        prose = TAG_RUN_RE.sub("", rest).strip() != ""   # còn chữ (ngoài hashtag) sau thẻ này trên cùng dòng?
        return " ".join(keep + ([t[1:] for t in drop] if prose else []))

    out = TAG_RUN_RE.sub(run, text)
    if not changed:
        return text
    out = re.sub(r"[ \t]+(?=\n|\Z)", "", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def build_caption(folder: Path) -> str:
    """Nội dung sẽ đăng lên Facebook.

    - Nếu có caption.txt (bạn đã sửa tay) thì dùng đúng nội dung đó, không cắt hashtag.
    - Ngược lại dùng mô tả của video (thường đã chứa tiêu đề và hashtag), không có mô tả thì dùng tiêu đề,
      giữ tối đa 5 hashtag đầu tiên (bỏ thẻ trùng).
    - Không ghép thêm hashtag, trừ khi nội dung hoàn toàn không có hashtag nào.
    """
    custom = _read(folder / "caption.txt")
    if custom:
        return custom[:MAX_CAPTION]
    caption = limit_hashtags(_read(folder / "description.txt") or _read(folder / "title.txt"))
    if not HASHTAG_RE.search(caption):
        tags = [t for t in _read(folder / "hashtags.txt").splitlines() if t.strip() and len(t) <= 25][:max_hashtags() or DEFAULT_MAX_HASHTAGS]
        if tags:
            caption = (caption + "\n\n" + " ".join(tags)).strip()
    return caption[:MAX_CAPTION]


def _video_info(root: Path, vdir: Path, channel_dir: Path | None) -> dict:
    rel = vdir.relative_to(root).as_posix()
    m = DATE_RE.match(vdir.name)
    date = m.group(1) if m else ""
    scheduled = None
    sched: dict = {}
    comment_state, comment_error = "", ""
    page_id, page_name = "", ""
    sj = vdir / "scheduled.json"
    if sj.exists():
        try:
            sched = json.loads(sj.read_text(encoding="utf-8"))
            if not isinstance(sched, dict):   # file hỏng thành "null" / danh sách
                raise ValueError("scheduled.json không phải đối tượng JSON")
            scheduled = sched.get("scheduled_for") or "?"
        except (ValueError, OSError):
            sched = {}
            scheduled = "?"
        comment_state, comment_error = commenter.comment_status(vdir, sched)
        pg = pages.resolve(sched)
        page_id = pg["id"] if pg else ""
        page_name = pages.page_label(sched)
    has_permission = bool(channel_dir and (channel_dir / "permission.json").exists())
    size = (vdir / "video.mp4").stat().st_size
    plain = re.sub(r"\s+", " ", HASHTAG_RE.sub("", build_caption(vdir))).strip()
    return {
        "rel": rel,
        "channel": channel_dir.name if channel_dir else "",
        "folder": vdir.name,
        "title": plain or vdir.name,
        "custom_caption": bool(_read(vdir / "caption.txt")),
        "date": f"{date[:4]}-{date[4:6]}-{date[6:]}" if date else "",
        "size_mb": round(size / 1048576, 1),
        "scheduled": scheduled,
        "yt_id": yt_id(vdir),
        "affiliate": bool(_read(vdir / "affiliate.txt")),
        "publish_status": sched.get("publish_status", ""),
        "publish_detail": sched.get("publish_detail", ""),
        "publish_checked_at": sched.get("publish_checked_at", ""),
        "permalink": sched.get("permalink", ""),
        "overdue": publish.overdue(sched) if sched else False,
        "page_id": page_id,
        "page_name": page_name,
        "comment_status": comment_state,
        "comment_error": comment_error,
        "has_permission": has_permission,
        "has_audio": (vdir / "audio.mp3").exists(),
        "reel_check": reelcheck.summary(vdir),
    }


def scan(page_id: str | None = None) -> dict:
    """Quét thư mục video. Mỗi thư mục kênh thuộc đúng một Page (file channel.json).

    Thư mục chưa gán mà mọi video đã hẹn trong đó đều của cùng một Page thì tự gán cho Page đó.
    page_id: chỉ trả về thư mục/video của Page này; "unassigned" trả về danh sách thư mục chưa gán
    ở mọi trường hợp. page_id=None trả về tất cả (dùng cho lịch tổng hợp, tổng quan).
    """
    root = config.output_dir()
    videos: list[dict] = []
    infos: list[dict] = []
    if not root.exists():
        return {"root": str(root), "exists": False, "channels": [], "channel_info": [], "unassigned": [], "videos": []}

    for p in sorted(root.iterdir()):
        if not p.is_dir():
            continue
        if (p / "video.mp4").exists():  # video nằm trực tiếp trong thư mục gốc (tải từ bản cũ): theo Page đã hẹn nó
            v = _video_info(root, p, None)
            v["owner"] = v["page_id"]
            videos.append(v)
            continue
        group = [_video_info(root, v, p) for v in sorted(p.iterdir()) if v.is_dir() and (v / "video.mp4").exists()]
        if not group:
            continue
        owner = owner_of(p)
        if owner and not pages.get(owner):
            owner = ""   # Page đã bị xóa khỏi app: thư mục quay về trạng thái chưa gán
        if not owner:
            scheduled_pages = {v["page_id"] for v in group if v["scheduled"]}
            if len(scheduled_pages) == 1 and "" not in scheduled_pages:
                owner = scheduled_pages.pop()
                try:
                    set_owner(p, owner)
                except OSError:
                    pass
        for v in group:
            v["owner"] = owner
        videos.extend(group)
        infos.append({
            "name": p.name, "owner": owner, "videos": len(group),
            "scheduled": sum(1 for v in group if v["scheduled"]),
            "pages": sorted({v["page_id"] for v in group if v["scheduled"] and v["page_id"]}),
        })

    unassigned = [i for i in infos if not i["owner"]]
    if page_id:
        infos = [i for i in infos if i["owner"] == page_id]
        videos = [v for v in videos if v["owner"] == page_id]
    return {
        "root": str(root), "exists": True,
        "channels": [i["name"] for i in infos], "channel_info": infos,
        "unassigned": unassigned, "videos": videos,
    }


def assign_channel(name: str, page_id: str) -> dict:
    """Gán thư mục kênh cho một Page. Không đổi Page của thư mục đang có video đã hẹn cho Page khác."""
    if not pages.get(page_id):
        raise ValueError("Không tìm thấy Fanpage.")
    root = config.output_dir().resolve()
    d = (root / (name or "")).resolve()
    if not name or d.parent != root or not d.is_dir() or (d / "video.mp4").exists():
        raise ValueError("Không tìm thấy thư mục.")
    cur = owner_of(d)
    if cur == page_id:
        return {"name": d.name, "owner": page_id}
    others = set()
    for v in d.iterdir():
        sj = v / "scheduled.json"
        if v.is_dir() and sj.exists():
            sched = commenter.read_sched(v)
            pg = pages.resolve(sched)
            if pg and pg["id"] != page_id:
                others.add(pages.label(pg))
    if others:
        raise ValueError(
            "Thư mục này có video đã hẹn giờ cho Page khác (" + ", ".join(sorted(others)) + "). "
            "Hãy chờ các video đó đăng xong, hoặc hẹn lại chúng, trước khi đổi Page."
        )
    set_owner(d, page_id)
    return {"name": d.name, "owner": page_id}


def owner_of_video(rel: str) -> str:
    """Page sở hữu một video (theo thư mục kênh chứa nó)."""
    d = resolve(rel)
    root = config.output_dir().resolve()
    parent = d.parent
    return owner_of(parent) if parent != root else ""


def resolve(rel: str) -> Path:
    """Đổi đường dẫn tương đối thành thư mục video, bảo đảm nằm trong thư mục gốc."""
    if not isinstance(rel, str) or not rel.strip():
        raise ValueError(f"Không tìm thấy video: {rel}")
    root = config.output_dir().resolve()
    path = (root / rel).resolve()
    if root not in path.parents or not (path / "video.mp4").exists():
        raise ValueError(f"Không tìm thấy video: {rel}")
    return path


def get_text(rel: str) -> dict:
    d = resolve(rel)
    own_comment = commenter.raw_video_comment(d)
    return {
        "caption": build_caption(d),
        "custom": bool(_read(d / "caption.txt")),
        # ô comment: chỉ comment riêng của video (có thể là "-"); trống = chọn ngẫu nhiên trong kho
        "comment": own_comment if own_comment is not None else "",
        "comment_custom": own_comment is not None,
        "affiliate": commenter.read_link(d),
    }


def save_text(rel: str, caption: str) -> None:
    """Lưu nội dung bài đăng vào caption.txt. Để trống = khôi phục mặc định (xóa caption.txt)."""
    d = resolve(rel)
    path = d / "caption.txt"
    caption = (caption or "").strip()
    if caption:
        path.write_text(caption[:MAX_CAPTION], encoding="utf-8")
    elif path.exists():
        path.unlink()
