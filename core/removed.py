"""Xoá video (cả thư mục, chuyển vào Thùng rác của macOS) và sổ ghi các video đã xoá.

Việc "đã tải chưa" của downloader dựa vào thư mục đang có; xoá thư mục thì mất dấu. Sổ này (removed_videos.json)
giữ ID + link + tiêu đề của video đã xoá để lần tải sau tự bỏ qua (trừ khi chọn tải lại).
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path

from . import commenter, config, library

STATE_FILE = config.ROOT / "removed_videos.json"
MAX_BATCH = 500
_lock = threading.Lock()

# Đã đăng thì xoá được khi việc tự comment đã xong hoặc không còn làm nữa; còn chờ comment thì giữ thư mục lại
_COMMENT_FINISHED = ("done", "expired", "none", "error", "skipped")


class DeleteError(Exception):
    """Lỗi hiện cho người dùng."""


# ---------- sổ video đã xoá ----------
def _load() -> dict:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".removed-", suffix=".tmp", dir=str(STATE_FILE.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, STATE_FILE)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def ids() -> dict:
    """{ID video: bản ghi} của mọi video đã xoá."""
    with _lock:
        return _load()


def listing() -> list[dict]:
    with _lock:
        data = _load()
    return sorted(({"id": k, **v} for k, v in data.items() if isinstance(v, dict)), key=lambda r: r.get("removed_at", ""), reverse=True)


def remember(rec: dict) -> None:
    vid = str(rec.get("id") or "")
    if not vid:
        return
    with _lock:
        data = _load()
        data[vid] = {k: v for k, v in rec.items() if k != "id"}
        _save(data)


def forget(vid: str) -> bool:
    """Bỏ một video khỏi sổ (cho phép tải lại)."""
    with _lock:
        data = _load()
        if vid not in data:
            return False
        del data[vid]
        _save(data)
        return True


def note(rec: dict | None) -> str:
    """Mô tả ngắn một bản ghi để ghi nhật ký: 'đã tải và xoá ngày ..., thư mục ...'."""
    rec = rec if isinstance(rec, dict) else {}
    when = str(rec.get("removed_at", ""))[:10]
    return f"đã tải và xoá ngày {when}" + (f", thư mục {rec['folder']}" if rec.get("folder") else "")


# ---------- xoá ----------
def _parse_time(value):
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.astimezone()   # giờ không kèm múi: coi là giờ máy


def blocked_reason(folder: Path) -> str:
    """Lý do không được xoá video này ("" = xoá được)."""
    sj = folder / "scheduled.json"
    if not sj.exists():
        return ""
    try:
        sched = json.loads(sj.read_text(encoding="utf-8"))
        if not isinstance(sched, dict):
            raise ValueError
    except (OSError, ValueError):
        return "Video có lịch đăng nhưng không đọc được trạng thái lịch: kiểm tra trong Fanpage trước."
    if sched.get("publish_status") != "published":
        return "Video đã hẹn lên lịch: huỷ lịch trong Fanpage trước khi xoá."
    state, _ = commenter.comment_status(folder, sched)
    if state not in _COMMENT_FINISHED and not comment_window_over(sched):
        return "Video đã đăng nhưng app còn chờ tự comment link: đợi comment xong rồi xoá."
    return ""


def comment_window_over(sched: dict, now: datetime | None = None) -> bool:
    """Đã quá hạn tự comment (commenter.MAX_AGE_DAYS sau giờ đăng): app không comment nữa dù trạng thái chưa kịp ghi
    "quá hạn" (ví dụ Page đang tắt tự động comment nên không có ai ghi)."""
    posted = _parse_time(sched.get("scheduled_for"))
    now = now or datetime.now().astimezone()
    return posted is not None and posted <= now - timedelta(days=commenter.MAX_AGE_DAYS, hours=1)


def _source_url(folder: Path) -> tuple[str, str]:
    try:
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "", ""
    if not isinstance(meta, dict):
        return "", ""
    return str(meta.get("source_url") or ""), str(meta.get("platform") or "")


def _title(folder: Path) -> str:
    try:
        t = (folder / "title.txt").read_text(encoding="utf-8").strip()
    except OSError:
        t = ""
    return (t.split("\n")[0] if t else folder.name)[:200]


def _to_trash(folder: Path) -> None:
    """Chuyển thư mục vào Thùng rác (khôi phục được). Không xoá hẳn: chuyển không được thì báo lỗi."""
    trash = Path.home() / ".Trash"
    if trash.is_dir():
        dest = trash / folder.name
        n = 1
        while dest.exists():
            n += 1
            dest = trash / f"{folder.name} ({n})"
        try:
            os.rename(folder, dest)   # cùng ổ đĩa: đổi chỗ tức thì
            return
        except OSError:
            pass                       # khác ổ đĩa hoặc macOS chặn quyền: nhờ Finder chuyển vào Thùng rác của ổ đó
    script = ['on run argv', 'tell application "Finder" to delete (POSIX file (item 1 of argv) as alias)', 'end run']
    cmd = ["osascript"] + [a for line in script for a in ("-e", line)] + [str(folder)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DeleteError(f"Không chuyển được vào Thùng rác: {exc}") from exc
    if r.returncode != 0 or folder.exists():
        raise DeleteError("Không chuyển được vào Thùng rác" + (f": {r.stderr.strip()[:200]}" if r.stderr.strip() else "") +
                          ". Nếu macOS hỏi quyền cho app điều khiển Finder, hãy cho phép rồi thử lại.")


def delete_video(rel: str) -> dict:
    """Xoá một video: chuyển cả thư mục video vào Thùng rác, ghi ID + link vào sổ. Trả về bản ghi."""
    folder = library.resolve(rel)   # ValueError nếu không có / nằm ngoài thư mục gốc
    root = config.output_dir().resolve()
    if folder == root or root not in folder.parents:
        raise DeleteError("Chỉ xoá được thư mục của một video.")
    why = blocked_reason(folder)
    if why:
        raise DeleteError(why)
    vid = library.yt_id(folder)
    url, platform = _source_url(folder)
    rec = {
        "id": vid, "url": url, "platform": platform,
        "title": _title(folder),
        "folder": folder.relative_to(root).as_posix(),
        "page_id": library.owner_of(folder.parent) if folder.parent != root else "",
        "removed_at": datetime.now().isoformat(timespec="seconds"),
    }
    _to_trash(folder)
    remember(rec)   # ghi sau khi đã chuyển được: chuyển lỗi thì video vẫn còn, không ghi nhầm là đã xoá
    return rec


# ---------- tự xoá sau khi đăng (cài theo từng thư mục kênh) ----------
SWEEP_EVERY = 30 * 60          # giây giữa hai lần quét
RETRY_AFTER = 6 * 3600         # xoá lỗi (ví dụ macOS chặn Thùng rác) thì 6 giờ sau mới thử lại video đó
CREATED_MIN_HOURS = 25         # lần gọi API đăng phải cũ hơn mức này (giới hạn 24 giờ của Page đếm theo scheduled.json)
_failed: dict[str, float] = {}
_last_sweep = 0.0


def due_for_delete(folder: Path, days: int, now: datetime | None = None) -> bool:
    """Video đã đăng, đã comment xong, giờ đăng cũ hơn `days` ngày và lần hẹn giờ cũ hơn 25 giờ."""
    if blocked_reason(folder) or not (folder / "scheduled.json").exists():
        return False
    try:
        sched = json.loads((folder / "scheduled.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(sched, dict):
        return False
    now = now or datetime.now().astimezone()
    posted = _parse_time(sched.get("scheduled_for"))
    created = _parse_time(sched.get("created_at")) or posted
    if posted is None or created is None:
        return False   # không rõ giờ đăng: không đoán, giữ lại
    return posted <= now - timedelta(days=days) and created <= now - timedelta(hours=CREATED_MIN_HOURS)


def sweep(log, now: datetime | None = None, force: bool = False) -> int:
    """Xoá (vào Thùng rác) các video đủ điều kiện trong mọi thư mục kênh đã bật tự xoá. Trả về số video đã xoá.
    log: hàm ghi nhật ký một dòng."""
    import time as _time
    global _last_sweep
    if not force and _time.time() - _last_sweep < SWEEP_EVERY:
        return 0
    _last_sweep = _time.time()
    from . import pages
    root = config.output_dir()
    if not root.exists():
        return 0
    n = 0
    for ch in sorted(root.iterdir()):
        if not ch.is_dir():
            continue
        ad = library.auto_delete_of(ch)
        owner = library.owner_of(ch)
        if not ad["enabled"] or not owner or not pages.get(owner):
            continue
        for v in sorted(ch.iterdir()):
            if not v.is_dir() or not (v / "video.mp4").exists():
                continue
            rel = v.relative_to(root).as_posix()
            if _time.time() - _failed.get(rel, 0) < RETRY_AFTER:
                continue
            if not due_for_delete(v, ad["days"], now):
                continue
            try:
                delete_video(rel)
            except (ValueError, DeleteError, OSError) as exc:
                _failed[rel] = _time.time()
                log(f"Tự xoá sau khi đăng: không xoá được {rel}: {exc} (thử lại sau 6 giờ)")
                continue
            _failed.pop(rel, None)
            n += 1
            log(f"Tự xoá sau khi đăng ({ad['days']} ngày): đã chuyển {rel} vào Thùng rác.")
    return n
