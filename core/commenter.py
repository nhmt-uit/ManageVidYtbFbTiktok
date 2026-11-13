"""Tự động comment (ví dụ link affiliate) vào bài sau khi bài đến giờ đăng.

Nội dung comment của mỗi video, theo thứ tự ưu tiên:
  1. comment.txt trong thư mục video (nếu là "-" thì video này không comment)
  2. Kho comment của Fanpage đã đăng video đó (Cài đặt > Cài đặt Page): chọn ngẫu nhiên một câu
     khi đến lúc comment, cố gắng không trùng câu vừa dùng ngay trước đó.

Câu đã chọn được lưu vào scheduled.json (comment_text) nên các lần thử lại vẫn dùng đúng câu đó.
Trạng thái lưu thêm vào scheduled.json của từng video (comment_id, comment_attempts, ...).
Facebook chỉ cho comment sau khi bài đã đăng, nên tiến trình nền chờ đến giờ hẹn + vài phút.
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from . import config, fbgate, pages, publish, ratelimit

COMMENT_MAX = 2000
MAX_ATTEMPTS = 6      # số lần thử tối đa cho mỗi video
MAX_AGE_DAYS = 3      # quá hạn này thì bỏ, không comment muộn
_lock = threading.Lock()
worker_job = None


class CommentError(Exception):
    def __init__(self, message="", block_hours: int = 0, maybe_gone: bool = False, limited: bool = False):
        super().__init__(message)
        self.block_hours = block_hours   # > 0: Facebook đang giới hạn tần suất, nên tạm dừng
        self.maybe_gone = maybe_gone     # Facebook báo "object does not exist": có thể bài đã bị xóa
        self.limited = limited           # True: app (cổng fbgate) chưa gửi gì vì đang giới hạn lượt gọi; không tính là một lần thử


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def raw_video_comment(folder: Path):
    """Nội dung comment riêng của video (có thể là "-"), hoặc None nếu chưa đặt."""
    text = _read(folder / "comment.txt")
    return text or None


# ---------- Link affiliate riêng của video ----------
LINK_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)
LINK_MAX = 500


def clean_link(text: str) -> str:
    """Trả về link hợp lệ (http/https) hoặc ném ValueError. Rỗng nghĩa là xóa link."""
    t = (text or "").strip()
    if not t:
        return ""
    if len(t) > LINK_MAX or not LINK_RE.match(t):
        raise ValueError("Link phải bắt đầu bằng http:// hoặc https:// và không chứa khoảng trắng.")
    return t


def read_link(folder: Path) -> str:
    return _read(folder / "affiliate.txt")


def save_link(folder: Path, text: str) -> str:
    link = clean_link(text)
    path = folder / "affiliate.txt"
    if link:
        path.write_text(link, encoding="utf-8")
    elif path.exists():
        path.unlink()
    return link


def eligible_pool(folder: Path, page_id: str) -> list[str]:
    """Các câu trong kho dùng được cho video này: câu có {link} chỉ dùng khi video có link affiliate."""
    link = read_link(folder)
    return [c for c in pages.read_pool(page_id) if link or "{link}" not in c]


def compose(item: str, link: str) -> str:
    """Thay {link} bằng link của video; câu không có {link} mà video có link thì thêm link xuống dòng cuối."""
    if "{link}" in item:
        return item.replace("{link}", link)[:COMMENT_MAX]
    if link:
        return (item + "\n" + link)[:COMMENT_MAX]
    return item[:COMMENT_MAX]


def has_comment(folder: Path, page_id: str) -> bool:
    """Video này có comment để gửi không (riêng của video, hoặc kho comment của Page có câu dùng được)."""
    own = raw_video_comment(folder)
    if own is not None:
        return own != "-"
    return bool(eligible_pool(folder, page_id))


def resolve_comment(folder: Path, sched: dict, page_id: str) -> str:
    """Nội dung sẽ gửi. Riêng của video > câu đã chọn trước đó (khi thử lại) > chọn ngẫu nhiên từ kho + link."""
    own = raw_video_comment(folder)
    if own is not None:
        return "" if own == "-" else own[:COMMENT_MAX]
    prev = (sched.get("comment_text") or "").strip()
    if prev:
        return prev[:COMMENT_MAX]
    items = eligible_pool(folder, page_id)
    if not items:
        return ""
    return compose(pages.pick_random(page_id, items), read_link(folder))


def save_video_comment(folder: Path, text: str) -> None:
    """Để trống = dùng comment mặc định (xóa comment.txt)."""
    path = folder / "comment.txt"
    text = (text or "").strip()
    if text:
        path.write_text(text[:COMMENT_MAX], encoding="utf-8")
    elif path.exists():
        path.unlink()


# ---------- Trạng thái trong scheduled.json ----------
def read_sched(folder: Path) -> dict:
    p = folder / "scheduled.json"
    if not p.exists():
        return {}
    return read_sched_file(p)


def read_sched_file(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}   # file hỏng thành "null" / danh sách thì coi như trống, không để nơi gọi .get() bị sập


def write_sched(folder: Path, data: dict) -> None:
    p = folder / "scheduled.json"
    tmp = folder / "scheduled.json.tmp"
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def _parse(iso):
    try:
        d = datetime.fromisoformat(iso)
        d = d if d.tzinfo else d.astimezone()
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    return d if 1971 <= d.year <= 2100 else None   # ngày vô lý (dữ liệu hỏng) không được làm sập phép cộng/trừ giờ ở nơi gọi


def comment_status(folder: Path, sched: dict):
    """Trả về (trạng thái, ghi chú lỗi). Trạng thái: done | expired | none | error | retry | pending."""
    if sched.get("comment_id"):
        return "done", ""
    if sched.get("comment_status") == "expired":
        return "expired", ""
    page = pages.resolve(sched)
    if not has_comment(folder, page["id"] if page else ""):
        return "none", ""
    if page is None:
        return "error", "Fanpage này đã bị xóa khỏi app."
    if sched.get("publish_status") in publish.NO_COMMENT:
        return "skipped", sched.get("publish_detail", "")
    err = sched.get("comment_error", "")
    if int(sched.get("comment_attempts", 0) or 0) >= MAX_ATTEMPTS:
        return "error", err
    if err:
        return "retry", err
    return "pending", ""


# ---------- Gọi Facebook ----------
def post_comment(page_id: str, token: str, video_id: str, message: str) -> str:
    last, gone = "không rõ lỗi", False
    for target in (video_id, f"{page_id}_{video_id}"):
        try:
            r = fbgate.request(
                "post",
                f"{config.graph_url()}/{target}/comments",
                cls="comment",
                data={"message": message, "access_token": token},
                timeout=60,
            )
        except fbgate.RateLimited as exc:
            raise CommentError(str(exc), limited=True) from None
        except requests.RequestException as exc:
            raise CommentError(f"Lỗi mạng khi gửi comment ({type(exc).__name__})") from None
        try:
            data = r.json()
        except ValueError:
            last = f"phản hồi không phải JSON ({r.status_code})"
            continue
        if r.status_code < 400 and data.get("id"):
            return data["id"]
        err = data.get("error", {}) if isinstance(data, dict) else {}
        last = f"{err.get('message', data)} (code {err.get('code')})"
        gone = err.get("code") == 803 or "does not exist" in str(err.get("message", "")).lower()
        hours = ratelimit.block_hours(err.get("code"), err.get("error_subcode"), err.get("message"))
        if err.get("code") in ratelimit.CALL_LIMIT_CODES:   # giới hạn lượt gọi của cả app: cổng fbgate đã dừng mọi lệnh gọi, không đánh dấu riêng Page
            raise CommentError(last, limited=True)
        if hours:   # Page bị Facebook giới hạn: dừng ngay, thử ID khác chỉ làm tình hình tệ hơn
            raise CommentError(last, block_hours=hours)
        if err.get("code") in (190, 10, 200, 368):  # token, thiếu quyền, bị chặn: đổi ID cũng vô ích
            break
    raise CommentError(last, maybe_gone=gone)


def _notify(title: str, body: str, key: str, ttl_hours: float = 24) -> None:
    try:
        from . import notify
        notify.send(title, body, key=key, ttl_hours=ttl_hours)
    except Exception:  # noqa: BLE001
        pass


def _skip_reason(state: str) -> str:
    return "Bài không còn trên Facebook (đã bị xóa?) nên không comment." if state == "missing" else "Bài đăng bị lỗi nên không comment."


def _notify_bad_status(folder: Path, sched: dict, prev: str, state: str) -> None:
    """Báo khi bài đăng chuyển sang trạng thái lỗi hoặc không còn trên Facebook."""
    if state in publish.BAD and prev not in publish.BAD:
        pg = pages.resolve(sched)
        label = pages.label(pg) if pg else "Fanpage"
        if state == "missing":
            if not publish.due(sched):
                return   # chưa đến giờ hẹn mà bài biến mất: gần như chắc là bạn tự xóa, không cần báo
            title = f"Bài không còn trên Facebook: {label}"
            body = f"{folder.name[:90]}\nApp sẽ không comment cho bài này. Nếu bạn tự xóa thì bỏ qua; muốn đăng lại thì vào mục Video, bấm Hẹn lại."
        else:
            title = f"Bài đăng bị lỗi: {label}"
            body = f"{folder.name[:90]}\n{(sched.get('publish_detail') or 'Facebook không đăng được bài này.')[:250]}\nVào Thư viện, bấm Hẹn lại để hẹn lại."
        _notify(title, body, key=f"bad:{sched.get('video_id') or folder.name}")


def _log(job, msg: str) -> None:
    if job is not None:
        job.log(msg)


def process(job, folder: Path, force: bool = False):
    """Comment cho một video nếu đã đến lúc. Trả về (trạng thái, thông báo)."""
    with _lock:
        sched = read_sched(folder)
        video_id = sched.get("video_id")
        if not video_id:
            return "none", "Video chưa được hẹn giờ."
        if sched.get("comment_id"):
            return "done", "Đã comment rồi."
        page = pages.resolve(sched)
        if page is None:
            return "failed", "Fanpage của video này đã bị xóa khỏi app."
        if not has_comment(folder, page["id"]):
            return "none", "Video này chưa có nội dung comment."

        now = datetime.now(timezone.utc)
        if force:
            sched.pop("comment_status", None)
            sched["comment_attempts"] = 0
            sched.pop("comment_next_try", None)
        else:
            when = _parse(sched.get("scheduled_for"))
            if when is None:
                return "wait", "Không đọc được giờ hẹn."
            if sched.get("comment_status") == "expired":
                return "expired", ""
            if now < when + timedelta(minutes=pages.effective(page)["comment_delay_minutes"]):
                return "wait", ""
            if now > when + timedelta(days=MAX_AGE_DAYS):
                sched["comment_status"] = "expired"
                write_sched(folder, sched)
                _log(job, f"Quá hạn {MAX_AGE_DAYS} ngày, bỏ qua comment: {folder.name}")
                pg = pages.resolve(sched)
                _notify(f"Comment bị bỏ qua: {pages.label(pg) if pg else 'Fanpage'}",
                        f"{folder.name[:90]}\nQuá {MAX_AGE_DAYS} ngày sau giờ đăng mà chưa comment được.", key=f"cexp:{video_id}")
                return "expired", "Quá hạn comment."
            if int(sched.get("comment_attempts", 0) or 0) >= MAX_ATTEMPTS:
                return "error", sched.get("comment_error", "")
            nxt = _parse(sched.get("comment_next_try"))
            if nxt and now < nxt:
                return "wait", ""
            # Chỉ comment khi Facebook xác nhận bài đã đăng. Nếu không đọc được trạng thái ("unknown")
            # hoặc bài vẫn "chưa đăng" quá 30 phút sau giờ hẹn thì cứ thử comment như trước.
            ps = sched.get("publish_status")
            if ps in publish.NO_COMMENT:
                return "skipped", sched.get("publish_detail") or _skip_reason(ps)
            if ps != "published":
                if not publish.fresh(sched, 180):
                    prev = sched.get("publish_status") or ""
                    res = publish.fetch(page, video_id)
                    if res.get("limited"):
                        return "limited", res.get("detail", "")   # chưa hỏi được Facebook: để vòng sau, không đổi trạng thái đã lưu
                    publish.apply(sched, res)
                    write_sched(folder, sched)
                    ps = res["state"]
                    _notify_bad_status(folder, sched, prev, ps)
                if ps in publish.NO_COMMENT:
                    _log(job, f"{_skip_reason(ps)} {folder.name}: {sched.get('publish_detail', '')}")
                    return "skipped", sched.get("publish_detail", "")
                if ps in ("scheduled", "processing") and now < when + timedelta(minutes=30):
                    return "wait", ""

        page_id, token = page["id"], page.get("token", "")
        if not token:
            return "failed", "Fanpage này chưa có Page token."

        message = resolve_comment(folder, sched, page_id)
        if not message:
            return "none", "Video này chưa có nội dung comment."
        sched["comment_text"] = message  # giữ nguyên câu này cho các lần thử lại
        try:
            cid = post_comment(page_id, token, video_id, message)
        except CommentError as exc:
            if exc.limited:   # cổng giới hạn lượt gọi hoặc Facebook báo giới hạn: chưa tính là một lần thử, để vòng sau (không ghi nhật ký từng video)
                return "limited", str(exc)
            if exc.maybe_gone and not exc.block_hours:
                # Facebook báo "object does not exist": hỏi lại trạng thái bài. Nếu bài đã bị xóa thì dừng hẳn,
                # không thử lại 6 lần và không báo "Comment thất bại".
                prev = sched.get("publish_status") or ""
                res = publish.fetch(page, video_id)
                if res.get("limited"):
                    return "limited", res.get("detail", "")
                if res["state"] == "missing":
                    publish.apply(sched, res)
                    write_sched(folder, sched)
                    _notify_bad_status(folder, sched, prev, "missing")
                    _log(job, f"{_skip_reason('missing')} {folder.name}")
                    return "skipped", sched.get("publish_detail", "")
            if exc.block_hours:
                pages.mark_blocked(page_id, exc.block_hours, str(exc))
                _log(job, f"Facebook đang giới hạn tần suất của Page {pages.label(page)}: tạm dừng comment {exc.block_hours} giờ.")
            attempts = int(sched.get("comment_attempts", 0) or 0) + 1
            sched["comment_attempts"] = attempts
            sched["comment_error"] = str(exc)
            sched["comment_next_try"] = (now + timedelta(minutes=min(5 * attempts, 30))).isoformat()
            write_sched(folder, sched)
            _log(job, f"Comment lỗi (lần {attempts}/{MAX_ATTEMPTS}) {folder.name}: {exc}")
            if attempts >= MAX_ATTEMPTS:
                _notify(f"Comment thất bại: {pages.label(page)}",
                        f"{folder.name[:90]}\nĐã thử {MAX_ATTEMPTS} lần không comment được: {str(exc)[:200]}", key=f"cfail:{video_id}")
            return "failed", str(exc)

        for k in ("comment_error", "comment_next_try", "comment_attempts", "comment_status"):
            sched.pop(k, None)
        sched["comment_id"] = cid
        sched["commented_at"] = now.isoformat()
        write_sched(folder, sched)
        _log(job, f"Đã comment: {folder.name}")
        return "posted", "Đã comment."


# ---------- Trạng thái đăng thật ----------
def refresh_status(folder: Path) -> str:
    """Hỏi Facebook trạng thái bài đăng của một video và lưu vào scheduled.json. Trả về trạng thái.

    Ném fbgate.RateLimited (không đổi gì trong scheduled.json) nếu app đang tự giới hạn lượt gọi hoặc Facebook báo giới hạn.
    """
    with _lock:
        sched = read_sched(folder)
        if not sched.get("video_id"):
            return ""
        page = pages.resolve(sched)
        if page is None:
            return "unknown"
        prev = sched.get("publish_status") or ""
        res = publish.fetch(page, sched["video_id"])
        if res.get("limited"):
            raise fbgate.RateLimited(res.get("detail", ""), res.get("minutes", 1), local=res.get("local", True))
        publish.apply(sched, res)
        write_sched(folder, sched)
        _notify_bad_status(folder, sched, prev, res["state"])
        return res["state"]


def reschedule(folder: Path) -> None:
    """Gỡ lịch cũ của video đã đăng lỗi hoặc không còn trên Facebook, để hẹn lại. Giữ bản cũ ở scheduled.old.json."""
    with _lock:
        sched = read_sched(folder)
        if not sched:
            raise ValueError("Video này chưa được hẹn giờ.")
        if sched.get("publish_status") not in publish.BAD:
            raise ValueError("Chỉ hẹn lại được video có trạng thái lỗi hoặc không tìm thấy trên Facebook. Bấm Kiểm tra trạng thái trước.")
        (folder / "scheduled.json").replace(folder / "scheduled.old.json")


def refresh_due(job, limit: int = 15) -> None:
    """Kiểm tra định kỳ các video đã đến giờ hẹn mà chưa được xác nhận là đã đăng.

    Video chưa đến giờ không tự hỏi Facebook (tốn lượt gọi): muốn biết sớm thì bấm Kiểm tra trạng thái trong Thư viện.
    """
    checked = 0
    for folder in find_scheduled():
        if checked >= limit:
            break
        sched = read_sched(folder)
        ps = sched.get("publish_status")
        if not sched.get("video_id") or ps in ("published", "error"):
            continue
        if pages.resolve(sched) is None:
            continue   # Fanpage đã bị xóa khỏi app: không có token để hỏi, tránh chiếm hết lượt kiểm tra mỗi vòng
        when = _parse(sched.get("scheduled_for"))
        if not publish.due(sched) or (when and datetime.now(timezone.utc) > when + timedelta(days=MAX_AGE_DAYS)):
            continue   # chưa đến giờ, hoặc quá cũ: không tự kiểm tra nữa (vẫn bấm tay được)
        # tránh gọi Facebook dày đặc: trạng thái chưa rõ hoặc "không thấy" thì hỏi lại thưa hơn
        if publish.fresh(sched, 3600 if ps in ("unknown", "missing") else 300):
            continue
        checked += 1
        try:
            state = refresh_status(folder)
        except fbgate.RateLimited:
            return   # đang giới hạn lượt gọi: bỏ cả vòng này, vòng sau (60 giây) thử lại, không thử hết từng video
        if state == "published":
            _log(job, f"Đã đăng: {folder.name}")
        elif state in publish.BAD:
            _log(job, f"Bài đăng có vấn đề ({state}): {folder.name}")


def CHECK_RESERVE() -> int:
    """Số lượt gọi trong giờ mà kiểm tra hàng loạt luôn chừa lại (một phần tư ngân sách)."""
    return max(10, fbgate.budget() // 4)


CHECK_PACE = 0.15          # nghỉ giữa hai lần hỏi Facebook khi kiểm tra cả đợt
CHECK_MAX_UNKNOWN = 5      # chừng này video liên tiếp không đọc được thì dừng (thường là mất mạng hoặc token hỏng)
CHECK_LABELS = (("published", "đã đăng"), ("scheduled", "chờ đến giờ"), ("processing", "đang xử lý"),
                ("error", "lỗi đăng"), ("missing", "không thấy trên Facebook"), ("unknown", "chưa xác định"))


def pending_folders(page_id: str = "") -> list[Path]:
    """Các video đã hẹn (của một Page, hoặc mọi Page) mà chưa được xác nhận là đã đăng, xếp theo giờ hẹn."""
    far = datetime.max.replace(tzinfo=timezone.utc)
    items = []
    for folder in find_scheduled():
        sched = read_sched(folder)
        if not sched.get("video_id") or sched.get("publish_status") == "published":
            continue
        if page_id and (pages.resolve(sched) or {}).get("id") != page_id:
            continue
        items.append((_parse(sched.get("scheduled_for")) or far, folder.name, folder))
    return [f for _, _, f in sorted(items, key=lambda t: (t[0], t[1]))]


def check_many(job, folders: list[Path]) -> str:
    """Hỏi Facebook lần lượt từng video trong danh sách (tác vụ nền), lưu trạng thái và trả về bản tóm tắt."""
    total = len(folders)
    job.set_progress(0, total)
    counts: dict = {}
    overdue = checked = unknown_run = limited_min = 0
    stopped = ""
    for i, folder in enumerate(folders, 1):
        if job.cancelled:
            job.log("Đã dừng theo yêu cầu.")
            stopped = "đã dừng giữa chừng"
            break
        try:
            with fbgate.keep_free(CHECK_RESERVE()):   # chừa lại một phần lượt gọi trong giờ cho hẹn giờ, huỷ, comment
                state = refresh_status(folder)
        except fbgate.RateLimited as exc:
            left = total - i + 1
            job.log(f"Dừng kiểm tra: {exc}")
            stopped = f"đã dừng vì app giới hạn lượt gọi Facebook, còn {left} video chưa kiểm tra (thử lại sau khoảng {exc.minutes} phút)"
            limited_min = exc.minutes
            break
        if state:   # rỗng = video vừa bị huỷ lịch hoặc không có video ID: bỏ qua, không tính
            checked += 1
            counts[state] = counts.get(state, 0) + 1
            sched = read_sched(folder)
            if state in ("scheduled", "processing") and publish.overdue(sched):
                overdue += 1
            if state == "published":
                job.log(f"Đã đăng: {folder.name}")
            elif state in publish.BAD:
                job.log(f"{'Lỗi đăng' if state == 'error' else 'Không thấy trên Facebook'}: {folder.name}")
            elif state == "unknown":
                job.log(f"Chưa xác định được: {folder.name}: {sched.get('publish_detail', '')[:150]}")
            unknown_run = unknown_run + 1 if state == "unknown" else 0
        job.set_progress(i, total)
        if unknown_run >= CHECK_MAX_UNKNOWN:
            job.log(f"{CHECK_MAX_UNKNOWN} video liên tiếp không đọc được trạng thái. Kiểm tra mạng hoặc token của Fanpage rồi thử lại.")
            stopped = f"dừng sớm vì {CHECK_MAX_UNKNOWN} video liên tiếp không đọc được (kiểm tra mạng hoặc token)"
            break
        if CHECK_PACE and i < total:
            job.cancel_event.wait(CHECK_PACE)
    job.data = {"checked": checked, "total": total, "counts": counts, "overdue": overdue, "stopped": bool(stopped),
                "limited_minutes": limited_min}
    if not total:
        return "Không có video nào cần kiểm tra (chưa có bài hẹn giờ, hoặc đều đã đăng)."
    bits = [f"{counts[k]} {label}" for k, label in CHECK_LABELS if counts.get(k)]
    msg = f"Đã kiểm tra {checked}/{total} video" + (": " + ", ".join(bits) if bits else "")
    if overdue:
        msg += f" (trong đó {overdue} bài quá giờ hẹn mà chưa đăng)"
    if stopped:
        msg += f"; {stopped}"
    bad = counts.get("missing", 0) + counts.get("error", 0)
    if bad:
        msg += f". {bad} bài có vấn đề nằm ở tab Lỗi / quá giờ, chọn rồi bấm Hẹn lại nếu muốn đăng lại"
    return msg + "."


# ---------- Tiến trình nền ----------
def find_scheduled():
    root = config.output_dir()
    if not root.exists():
        return []
    paths = list(root.glob("*/scheduled.json")) + list(root.glob("*/*/scheduled.json"))
    return sorted(p.parent for p in paths)


_limited_logged = 0.0


def _comment_round(job) -> int:
    """Một vòng comment cho mọi video đến hạn. Trả về số comment đã gửi. Bị giới hạn lượt gọi thì dừng cả vòng (ghi nhật ký một dòng, tối đa 10 phút một lần)."""
    global _limited_logged
    posted = 0
    for folder in find_scheduled():
        page = pages.resolve(read_sched(folder))
        if page is None or not page.get("auto_comment") or pages.blocked_until(page):
            continue   # Page đang bị Facebook giới hạn tần suất thì không comment thêm
        status, msg = process(job, folder)
        if status == "limited":
            if time.time() - _limited_logged > 600:
                _limited_logged = time.time()
                _log(job, f"Tạm hoãn comment cho tới khi hết giới hạn lượt gọi Facebook: {msg}")
            break
        if status == "posted":
            posted += 1
            time.sleep(max(0, pages.effective(page)["comment_gap_seconds"]))
    return posted


def _worker(job, manager) -> None:
    fbgate.mark_background()   # mọi lượt đọc trạng thái của luồng này tính vào phần ngân sách dành cho việc chạy nền
    job.log("Tự động comment: sẵn sàng. Bật/tắt cho từng Page ở Cài đặt > Cài đặt Page.")
    announced = None
    last_stock = 0.0
    gate_noted = False
    while not job.cancelled:
        wait_min = fbgate.paused()
        if wait_min and not gate_noted:
            job.log(f"Facebook đang giới hạn lượt gọi API: tạm dừng kiểm tra trạng thái và comment khoảng {wait_min} phút.")
        elif gate_noted and not wait_min:
            job.log("Hết thời gian tạm dừng, tiếp tục kiểm tra trạng thái và comment.")
        gate_noted = bool(wait_min)
        try:
            if not wait_min:
                refresh_due(job)
        except Exception as exc:  # noqa: BLE001
            job.log(f"Lỗi kiểm tra trạng thái đăng: {exc}")
        try:
            from . import ytdlp_update
            ytdlp_update.tick(manager, job)   # mỗi ngày kiểm tra và cập nhật yt-dlp (bật/tắt ở Cài đặt chung)
        except Exception as exc:  # noqa: BLE001
            job.log(f"Lỗi kiểm tra yt-dlp: {exc}")
        if time.time() - last_stock >= 3600:   # mỗi giờ kiểm tra kho video của các Page một lần
            last_stock = time.time()
            try:
                from . import stock
                stock.alerts(job)
            except Exception as exc:  # noqa: BLE001
                job.log(f"Lỗi kiểm tra kho video: {exc}")
        try:   # tự xoá video đã đăng ở các thư mục bật "Xoá video sau khi đăng" (tự giãn 30 phút một lần)
            from . import editor, removed
            if not (editor._busy.locked() or manager.has_running("schedule") or manager.has_running("cancel")):
                removed.sweep(job.log)
        except Exception as exc:  # noqa: BLE001
            job.log(f"Lỗi tự xoá video sau khi đăng: {exc}")
        names = sorted(pages.label(p) for p in pages.all_pages() if p.get("auto_comment") and p.get("token"))
        any_auto = bool(names)
        if names != announced:
            job.log("Tự động comment BẬT cho: " + ", ".join(names) if names else "Tự động comment: TẮT cho mọi Page.")
            announced = names
        if any_auto and not wait_min:
            try:
                _comment_round(job)
            except Exception as exc:  # noqa: BLE001
                job.log(f"Lỗi tiến trình comment: {exc}")
        job.cancel_event.wait(60)


def start_worker(manager) -> None:
    global worker_job
    worker_job = manager.create("comment-worker", "Tự động comment")
    threading.Thread(target=_worker, args=(worker_job, manager), daemon=True).start()
