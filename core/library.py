"""Quét thư mục video, đọc/sửa nội dung bài đăng."""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

from . import commenter, config, pages, publish, reelcheck, series
from .videofile import APPROVED, DRAFT, video_file

DATE_RE = re.compile(r"^(\d{8}) - ")
TAG_BODY = r"[\ẁ-ͯ]+"   # chữ + dấu rời (tiếng Việt gõ kiểu NFD: "a" + dấu) để không cắt hashtag giữa chữ
HASHTAG_RE = re.compile(r"#" + TAG_BODY, re.UNICODE)
MAX_CAPTION = 2000


YT_ID_RE = re.compile(r"\[([\w-]{11}|\d{15,20}|[0-9a-f]{24})\]\s*$")   # YouTube (11 ký tự), TikTok (dãy số dài), Rednote (24 ký tự hex)


OWNER_FILE = "channel.json"   # nằm trong thư mục kênh: {"targets": {"facebook": "<page_id>"}, "page_id": "...", "auto_delete": {...}}

# Nơi đăng của một thư mục: mỗi nền tảng tối đa một tài khoản. Hiện chỉ có Facebook; sau này thêm instagram, tiktok, youtube.
PLATFORMS = {"facebook": "Facebook"}


def targets_of(channel_dir) -> dict:
    """{nền tảng: ID tài khoản} của thư mục. File cũ chỉ có "page_id" thì hiểu là Facebook."""
    if channel_dir is None:
        return {}
    d = _read_owner_file(channel_dir)
    t = d.get("targets")
    if isinstance(t, dict):
        return {k: str(v) for k, v in t.items() if k in PLATFORMS and isinstance(v, (str, int)) and str(v)}
    pid = d.get("page_id")
    return {"facebook": str(pid)} if isinstance(pid, (str, int)) and str(pid) else {}


def has_explicit_targets(channel_dir) -> bool:
    """Thư mục đã được gán/bỏ gán theo kiểu mới (có khoá "targets"): khi đó không tự gán lại theo các video đã hẹn."""
    return isinstance(_read_owner_file(channel_dir).get("targets"), dict)


def owner_of(channel_dir) -> str:
    """Page Facebook của một thư mục kênh ("" nếu chưa gán)."""
    return targets_of(channel_dir).get("facebook", "")


def _read_owner_file(channel_dir) -> dict:
    try:
        d = json.loads((Path(channel_dir) / OWNER_FILE).read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return d if isinstance(d, dict) else {}


def _write_owner_file(channel_dir, data: dict) -> None:
    """Ghi channel.json kiểu nguyên tử (file tạm rồi đổi tên): file này quyết định thư mục thuộc Page nào."""
    path = Path(channel_dir) / OWNER_FILE
    tmp = path.with_name(f".{OWNER_FILE}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def set_target(channel_dir, platform: str, account_id: str) -> dict:
    """Đặt (hoặc bỏ, khi account_id rỗng) nơi đăng của thư mục trên một nền tảng. Giữ các cài đặt khác của thư mục."""
    if platform not in PLATFORMS:
        raise ValueError("Nền tảng chưa hỗ trợ.")
    data = _read_owner_file(channel_dir)
    t = targets_of(channel_dir)
    if account_id:
        t[platform] = str(account_id)
    else:
        t.pop(platform, None)
    data["targets"] = t
    if t.get("facebook"):
        data["page_id"] = t["facebook"]   # giữ khoá cũ để bản cũ của app vẫn đọc được
    else:
        data.pop("page_id", None)
    _write_owner_file(channel_dir, data)
    return t


def set_owner(channel_dir, page_id: str) -> None:
    set_target(channel_dir, "facebook", page_id)


# Tự xoá video sau khi đăng (cài theo từng thư mục kênh). Ít nhất 2 ngày: giới hạn 24 giờ và số bài mỗi ngày của Page
# được tính từ scheduled.json của các video, xoá sớm quá thì app đếm thiếu và có thể hẹn vượt giới hạn.
AUTO_DELETE_MIN_DAYS = 2
AUTO_DELETE_MAX_DAYS = 365
AUTO_DELETE_DEFAULT_DAYS = 3


def auto_delete_of(channel_dir) -> dict:
    ad = _read_owner_file(channel_dir).get("auto_delete")
    ad = ad if isinstance(ad, dict) else {}
    try:
        days = int(ad.get("days", AUTO_DELETE_DEFAULT_DAYS))
    except (TypeError, ValueError):
        days = AUTO_DELETE_DEFAULT_DAYS
    return {"enabled": ad.get("enabled") is True, "days": min(AUTO_DELETE_MAX_DAYS, max(AUTO_DELETE_MIN_DAYS, days))}


def set_auto_delete(channel_dir, enabled: bool, days: int) -> dict:
    if not (AUTO_DELETE_MIN_DAYS <= days <= AUTO_DELETE_MAX_DAYS):
        raise ValueError(f"Số ngày phải từ {AUTO_DELETE_MIN_DAYS} đến {AUTO_DELETE_MAX_DAYS}.")
    data = _read_owner_file(channel_dir)
    data["auto_delete"] = {"enabled": bool(enabled), "days": int(days)}
    _write_owner_file(channel_dir, data)
    return auto_delete_of(channel_dir)


def yt_id(folder: Path) -> str:
    """ID video (YouTube hoặc TikTok): lấy từ meta.json, hoặc từ đuôi [id] trong tên thư mục."""
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
    size = video_file(vdir).stat().st_size
    edited = (vdir / APPROVED).exists()
    has_draft = (vdir / DRAFT).exists()
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
        "edited": edited,
        "has_draft": has_draft,
        "has_subs": (vdir / "subs.json").exists(),
        "reel_check": reelcheck.summary(vdir),
        **series.info_for(vdir),   # phim / tập nhận từ tiêu đề (hoặc sửa tay); series.finalize gộp nhóm sau
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
        if not owner and not has_explicit_targets(p):   # chỉ tự gán thư mục kiểu cũ; thư mục bạn đã bỏ gán thì để nguyên
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
            "name": p.name, "owner": owner, "videos": len(group), "auto_delete": auto_delete_of(p),
            "scheduled": sum(1 for v in group if v["scheduled"]),
            "pages": sorted({v["page_id"] for v in group if v["scheduled"] and v["page_id"]}),
        })

    by_channel: dict[str, list[dict]] = {}
    for v in videos:
        by_channel.setdefault(v["channel"], []).append(v)
    for group_videos in by_channel.values():   # phim nhiều tập: gộp theo từng thư mục kênh (mỗi thư mục thuộc đúng một Page)
        series.finalize(group_videos)

    unassigned = [i for i in infos if not i["owner"]]
    if page_id:
        infos = [i for i in infos if i["owner"] == page_id]
        videos = [v for v in videos if v["owner"] == page_id]
    return {
        "root": str(root), "exists": True,
        "channels": [i["name"] for i in infos], "channel_info": infos,
        "unassigned": unassigned, "videos": videos,
    }


class PendingPosts(ValueError):
    """Thư mục còn video đang chờ đăng trên Page cũ: phải huỷ lịch (hoặc chờ đăng xong) trước khi đổi/bỏ Page."""

    def __init__(self, msg: str, page_id: str, rels: list[str]):
        super().__init__(msg)
        self.page_id, self.rels = page_id, rels


def folder_dir(name: str) -> Path:
    """Thư mục kênh theo tên (một cấp ngay dưới thư mục gốc). ValueError nếu không hợp lệ / không có."""
    root = config.output_dir().resolve()
    if not isinstance(name, str) or not name or name in (".", "..") or "/" in name or "\\" in name or name.startswith("."):
        raise ValueError("Không tìm thấy thư mục.")
    d = (root / name).resolve()
    if d.parent != root or not d.is_dir() or (d / "video.mp4").exists():
        raise ValueError("Không tìm thấy thư mục.")
    return d


def pending_posts(d: Path) -> dict:
    """{page_id: [rel, ...]} các video trong thư mục còn lịch chưa đăng xong (chờ đăng, quá giờ, lỗi, không thấy)."""
    root = config.output_dir().resolve()
    out: dict = {}
    for v in sorted(d.iterdir()):
        if not (v.is_dir() and (v / "scheduled.json").exists()):
            continue
        sched = commenter.read_sched(v)
        if sched.get("publish_status") == "published":
            continue
        pg = pages.resolve(sched)
        out.setdefault(pg["id"] if pg else str(sched.get("page_id") or ""), []).append(v.relative_to(root).as_posix())
    return out


def change_target(name: str, platform: str, account_id: str) -> dict:
    """Gán / đổi / bỏ nơi đăng của một thư mục. Video đã đăng giữ nguyên lịch sử; còn video chờ đăng trên tài khoản cũ
    thì từ chối (PendingPosts) để không bỏ rơi bài đang hẹn mà không ai quản lý."""
    d = folder_dir(name)
    if platform != "facebook":
        raise ValueError("Nền tảng chưa hỗ trợ.")
    account_id = str(account_id or "")
    if account_id and not pages.get(account_id):
        raise ValueError("Không tìm thấy Fanpage.")
    cur = owner_of(d)
    if cur == account_id:
        return {"name": d.name, "targets": targets_of(d)}
    pend = {pid: rels for pid, rels in pending_posts(d).items() if pid != account_id}
    if pend:
        pid, rels = max(pend.items(), key=lambda kv: len(kv[1]))
        pg = pages.get(pid)
        n = sum(len(r) for r in pend.values())
        raise PendingPosts(
            f"Thư mục còn {n} video chờ đăng trên Page {pages.label(pg) if pg else pid}. "
            "Huỷ lịch các video đó (hoặc chờ đăng xong) rồi mới đổi hoặc bỏ Page.", pid, rels)
    return {"name": d.name, "targets": set_target(d, "facebook", account_id)}


def assign_channel(name: str, page_id: str) -> dict:
    """Gán thư mục kênh cho một Page (giữ cho màn hình Tổng quan)."""
    if not pages.get(page_id):
        raise ValueError("Không tìm thấy Fanpage.")
    r = change_target(name, "facebook", page_id)
    return {"name": r["name"], "owner": r["targets"].get("facebook", "")}


def create_folder(name: str, page_id: str = "") -> dict:
    from .downloader import safe_name
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Chưa nhập tên thư mục.")
    if not re.sub(r'[\\/:*?"<>|.\s]', "", name):   # chỉ toàn dấu chấm / ký tự bị lọc: safe_name sẽ đổi thành "untitled"
        raise ValueError("Tên thư mục không hợp lệ.")
    clean = safe_name(name)
    if not clean or clean in (".", "..") or clean.startswith("."):
        raise ValueError("Tên thư mục không hợp lệ.")
    if page_id and not pages.get(page_id):
        raise ValueError("Không tìm thấy Fanpage.")
    root = config.output_dir()
    root.mkdir(parents=True, exist_ok=True)
    d = root / clean
    if d.exists():
        raise ValueError(f'Đã có thư mục "{clean}".')
    d.mkdir()
    set_target(d, "facebook", page_id)   # ghi rõ "targets" (kể cả rỗng) để không bị tự gán
    return {"name": clean, "targets": targets_of(d)}


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
    try:
        path = (root / rel).resolve()
        found = root in path.parents and (path / "video.mp4").exists()
    except (OSError, ValueError):   # tên quá dài, ký tự lạ...: coi như không có video này (đừng để thành lỗi 500)
        found = False
    if not found:
        raise ValueError(f"Không tìm thấy video: {rel[:80]}")
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


def folders_overview() -> list[dict]:
    """Mọi thư mục kênh (cả thư mục trống), kèm nơi đăng, cài đặt tự xoá và số video theo trạng thái."""
    root = config.output_dir()
    if not root.exists():
        return []
    by: dict = {}
    for v in scan(None)["videos"]:   # scan cũng tự gán thư mục kiểu cũ (giữ hành vi cũ) trước khi đọc nơi đăng bên dưới
        if v["channel"]:
            by.setdefault(v["channel"], []).append(v)
    out = []
    for d in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not d.is_dir() or d.name.startswith(".") or (d / "video.mp4").exists():
            continue
        vids = by.get(d.name, [])
        fb = owner_of(d)
        page = pages.get(fb) if fb else None
        out.append({
            "name": d.name,
            "targets": {"facebook": {"id": fb, "label": pages.label(page) if page else "", "missing": bool(fb and not page)}},
            "auto_delete": auto_delete_of(d),
            "videos": len(vids),
            "new": sum(1 for v in vids if not v["scheduled"]),
            "pending": sum(1 for v in vids if v["scheduled"] and v["publish_status"] != "published"),
            "published": sum(1 for v in vids if v["publish_status"] == "published"),
        })
    return out
