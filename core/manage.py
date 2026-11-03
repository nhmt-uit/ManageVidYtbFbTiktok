"""Huỷ lịch hoặc đổi giờ một bài đã hẹn giờ (chưa đăng).

Huỷ lịch:  xóa bài hẹn trên Facebook (DELETE /{video-id}), rồi gỡ scheduled.json trong app
           (giữ bản cũ ở scheduled.old.json). Video quay về trạng thái "Chưa lên lịch".
           Nếu Facebook từ chối xóa thì KHÔNG đổi gì trong app, để app và Facebook không bị lệch.
           Nếu bạn đã tự huỷ bài trong Meta Business Suite, dùng local_only=True để chỉ gỡ lịch trong app.
Đổi giờ:   thử sửa trực tiếp giờ hẹn trên Facebook (POST /{video-id} scheduled_publish_time).
           Nếu Facebook không cho, báo lại để người dùng chọn "huỷ rồi hẹn lại" (tải lại video lên).
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from . import commenter, config, fbgate, pages, publish, ratelimit


class ManageError(Exception):
    """Lỗi có thể hiện cho người dùng. refused=True: Facebook từ chối thao tác (không phải lỗi mạng/dữ liệu)."""

    def __init__(self, message: str, refused: bool = False):
        super().__init__(message)
        self.refused = refused


class RateLimited(ManageError):
    """Đang bị giới hạn lượt gọi: dừng ngay, KHÔNG phải bài bị từ chối.

    local=True: chính app tự dừng (hết ngân sách lượt gọi mỗi giờ), Facebook chưa hề báo gì.
    page_block=True: Facebook chặn riêng Page này (code 32, 368...), khác với giới hạn chung của cả app.
    """

    def __init__(self, message: str, hours: int = 1, local: bool = False, minutes: int = 0, page_block: bool = False):
        super().__init__(message, refused=False)
        self.hours = hours
        self.minutes = minutes or hours * 60
        self.local = local
        self.page_block = page_block


def _from_gate(exc: "fbgate.RateLimited") -> RateLimited:
    return RateLimited(str(exc), exc.hours, local=exc.local, minutes=exc.minutes)


def _load(folder: Path) -> tuple[dict, dict]:
    sched = commenter.read_sched(folder)
    if not sched:
        raise ManageError("Video này chưa được hẹn giờ.")
    page = pages.resolve(sched)
    if page is None:
        raise ManageError("Fanpage của video này đã bị xóa khỏi app.")
    return sched, page


def _check_not_published(folder: Path, sched: dict, page: dict) -> None:
    if sched.get("publish_status") == "published":
        raise ManageError("Bài này đã được đăng, không huỷ hay đổi giờ được nữa.")
    if publish.due(sched):   # đã quá giờ hẹn: hỏi Facebook xem đã đăng chưa trước khi thao tác
        try:
            st = commenter.refresh_status(folder)
        except fbgate.RateLimited as exc:
            raise _from_gate(exc) from None
        if st == "published":
            raise ManageError("Bài này vừa được đăng, không huỷ hay đổi giờ được nữa.")


def _fb_error(r: requests.Response) -> tuple[str, int | None]:
    try:
        data = r.json()
    except ValueError:
        return f"HTTP {r.status_code}", None
    err = data.get("error", {}) if isinstance(data, dict) else {}
    return config.redact(f"{err.get('message', data)} (code {err.get('code')})"), err.get("code")


def _check_rate_limit(r: requests.Response, msg: str) -> None:
    """Facebook báo giới hạn tần suất thì dừng hẳn: không coi là "bài bị từ chối" và không gọi thêm."""
    try:
        err = (r.json() or {}).get("error", {})
    except (ValueError, AttributeError):
        err = {}
    hours = ratelimit.block_hours(err.get("code"), err.get("error_subcode"), err.get("message"))
    if hours:
        page_block = err.get("code") not in ratelimit.CALL_LIMIT_CODES   # code 4/17/613: giới hạn của cả app, cổng fbgate đã dừng mọi lệnh gọi
        raise RateLimited(f"Facebook đang giới hạn số lượt gọi API, chưa làm gì với bài này: {msg}", hours,
                          minutes=max(fbgate.paused(), hours * 60 if page_block else 0), page_block=page_block)


def _gone(msg: str, code) -> bool:
    return code == 803 or "does not exist" in msg.lower() or "not exist" in msg.lower()


GONE_RECHECK_SECONDS = 3.0   # nghỉ giữa hai lần đọc lại trước khi tin "bài không còn" (lỗi thoáng qua của Facebook thường hết sau vài giây)
MAX_GONE_STREAK = 3          # liên tiếp bấy nhiêu bài "không còn" trong một đợt huỷ thì dừng để người dùng kiểm tra
_pause = threading.Event()   # chỉ để chờ (không bao giờ set)


class Outcome(str):
    """"deleted" / "gone" kèm .detail: câu trả lời gốc của Facebook, để ghi vào nhật ký và scheduled.old.json."""

    detail = ""


def _outcome(kind: str, detail: str = "") -> Outcome:
    o = Outcome(kind)
    o.detail = detail
    return o


def _expect_missing(st: dict, msg: str) -> None:
    """st là kết quả publish.fetch sau khi xóa báo "không tồn tại". Chỉ im lặng khi Facebook cũng KHÔNG thấy bài."""
    if st.get("limited"):
        raise RateLimited(st.get("detail", ""), max(1, -(-int(st.get("minutes", 1)) // 60)), local=bool(st.get("local", True)), minutes=int(st.get("minutes", 1)))
    if st["state"] == "missing":
        return
    if st["state"] == "unknown":
        raise ManageError(f"Facebook báo không còn bài nhưng app chưa xác nhận được ({st.get('detail', '')[:150]}). Chưa đổi gì, thử lại sau.")
    raise ManageError(f"Facebook không xóa được bài hẹn này dù bài vẫn còn (trạng thái: {st['state']}): {msg}", refused=True)


def fb_delete(page: dict, video_id: str) -> Outcome:
    """Xóa bài hẹn trên Facebook. Trả về "deleted" hoặc "gone" (Facebook báo không còn bài đó; .detail là câu gốc)."""
    token = page.get("token")
    if not token:
        raise ManageError("Fanpage này chưa có Page token. Vào mục Kết nối Fanpage để lấy lại.")
    try:
        r = fbgate.request("delete", f"{config.graph_url()}/{video_id}", params={"access_token": token}, timeout=60)
    except fbgate.RateLimited as exc:
        raise _from_gate(exc) from None
    except requests.RequestException as exc:
        raise ManageError(f"Không kết nối được Facebook ({type(exc).__name__}). Chưa đổi gì, thử lại sau.") from exc
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code < 400 and not (isinstance(data, dict) and "error" in data):
        if isinstance(data, dict) and data.get("success") is False:
            raise ManageError("Facebook trả về không thành công khi xóa bài hẹn.", refused=True)
        return _outcome("deleted")
    msg, code = _fb_error(r)
    _check_rate_limit(r, msg)
    if _gone(msg, code):
        # "Object does not exist" cũng là câu Facebook dùng khi không đủ quyền, khi thao tác không hỗ trợ, hoặc khi chính nó đang lỗi.
        # Gỡ bài khỏi app là việc khó hoàn lại (bài còn trên Facebook sẽ vẫn được đăng mà app không biết), nên chỉ tin khi:
        #   1) đọc lại bài: Facebook không thấy; 2) vài giây sau đọc lần nữa: vẫn không thấy;
        #   3) đọc được chính Page bằng cùng token (Facebook và token đang hoạt động bình thường).
        st = publish.fetch(page, video_id)
        _expect_missing(st, msg)
        _pause.wait(GONE_RECHECK_SECONDS)
        st = publish.fetch(page, video_id)
        _expect_missing(st, msg)
        pr = publish.probe(page)
        if pr.get("limited"):
            raise RateLimited(pr.get("detail", ""), max(1, -(-int(pr.get("minutes", 1)) // 60)), local=bool(pr.get("local", True)), minutes=int(pr.get("minutes", 1)))
        if not pr.get("ok"):
            raise ManageError(f"Facebook báo không còn bài nhưng cũng không đọc được chính Page ({str(pr.get('detail', ''))[:150]}), "
                              "nên chưa chắc bài đã mất (có thể Facebook hoặc token đang lỗi). Chưa đổi gì, thử lại sau.")
        return _outcome("gone", f"khi xóa Facebook trả: {msg}; đọc lại 2 lần cách nhau {GONE_RECHECK_SECONDS:g}s đều không thấy bài, đọc Page bình thường")
    raise ManageError(f"Facebook không cho xóa bài hẹn này: {msg}", refused=True)


def fb_retime(page: dict, video_id: str, when_ts: int) -> None:
    token = page.get("token")
    if not token:
        raise ManageError("Fanpage này chưa có Page token. Vào mục Kết nối Fanpage để lấy lại.")
    try:
        r = fbgate.request(
            "post",
            f"{config.graph_url()}/{video_id}",
            data={"scheduled_publish_time": str(when_ts), "published": "false", "access_token": token},
            timeout=60,
        )
    except fbgate.RateLimited as exc:
        raise _from_gate(exc) from None
    except requests.RequestException as exc:
        raise ManageError(f"Không kết nối được Facebook ({type(exc).__name__}). Chưa đổi gì, thử lại sau.") from exc
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code < 400 and not (isinstance(data, dict) and "error" in data):
        if isinstance(data, dict) and data.get("success") is False:
            raise ManageError("Facebook trả về không thành công khi đổi giờ.", refused=True)
        return
    msg, _ = _fb_error(r)
    _check_rate_limit(r, msg)
    raise ManageError(f"Facebook không cho đổi giờ trực tiếp: {msg}", refused=True)


def _remove_local(folder: Path, sched: dict, why: str, detail: str = "") -> None:
    with commenter._lock:
        sched = dict(sched)
        sched["cancelled_at"] = datetime.now(timezone.utc).isoformat()
        sched["cancel_reason"] = why
        if detail:   # bằng chứng: Facebook đã trả gì khi app kết luận "không còn bài" (để còn đối chiếu/khôi phục nếu sai)
            sched["cancel_detail"] = str(detail)[:600]
        old = folder / "scheduled.old.json"
        tmp = folder / "scheduled.old.json.tmp"
        tmp.write_text(json.dumps(sched, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(old)
        (folder / "scheduled.json").unlink(missing_ok=True)


def _cancel(folder: Path, local_only: bool = False) -> str:
    """Huỷ lịch một bài chưa đăng. Trả về "deleted" (đã xóa trên Facebook), "gone" (Facebook báo không còn bài) hoặc "local"."""
    sched, page = _load(folder)
    if not local_only:
        _check_not_published(folder, sched, page)
        vid = sched.get("video_id")
        if not vid:
            raise ManageError("Bản ghi hẹn giờ thiếu video ID, không xóa được trên Facebook. Dùng \"chỉ gỡ trong app\" nếu bạn đã tự huỷ.")
        res = fb_delete(page, vid)
        _remove_local(folder, commenter.read_sched(folder) or sched, "fb_" + res, getattr(res, "detail", ""))   # đọc lại: trạng thái có thể vừa được cập nhật
        return res
    if sched.get("publish_status") == "published":
        raise ManageError("Bài này đã được đăng, không gỡ lịch được.")
    vid = sched.get("video_id")
    if vid:   # chỉ gỡ trong app khi Facebook xác nhận bài không còn hẹn giờ, nếu không bài vẫn được đăng mà app không biết
        st = publish.fetch(page, vid)
        if st.get("limited"):
            raise RateLimited(st.get("detail", ""), max(1, -(-int(st.get("minutes", 1)) // 60)), local=bool(st.get("local", True)), minutes=int(st.get("minutes", 1)))
        if st["state"] in ("scheduled", "processing"):
            raise ManageError("Bài này VẪN còn hẹn giờ trên Facebook nên app không gỡ khỏi danh sách (nếu gỡ, bài vẫn được đăng mà app không biết). "
                              "Hãy huỷ bài trong Meta Business Suite (Nội dung đã lên lịch), rồi bấm Kiểm tra trạng thái.")
        if st["state"] == "published":
            raise ManageError("Facebook báo bài này đã được đăng, không gỡ lịch được.")
        if st["state"] == "unknown":
            raise ManageError(f"Chưa xác nhận được bài còn trên Facebook hay không ({st.get('detail', '')[:150]}). Chưa đổi gì, thử lại sau.")
    _remove_local(folder, sched, "local_only")
    return "local"


def cancel(folder: Path, local_only: bool = False) -> str:
    """Huỷ lịch một bài chưa đăng. local_only: chỉ gỡ trong app (người dùng đã tự huỷ trên Facebook)."""
    res = _cancel(folder, local_only)
    if res == "deleted":
        return "Đã huỷ bài hẹn trên Facebook và gỡ lịch trong app."
    if res == "gone":
        return "Facebook báo không còn bài hẹn này, đã gỡ lịch trong app."
    return "Đã gỡ lịch trong app (không gọi Facebook)."


PACE_SECONDS = 0.4          # nghỉ giữa hai lần gọi Facebook khi huỷ nhiều bài
MAX_NET_FAILS = 3           # lỗi kết nối liên tiếp thì dừng cả đợt


def cancel_many(job, page_id: str, rels: list[str], local_only: bool = False) -> str:
    """Huỷ lịch nhiều bài của một Page (tác vụ nền).

    Facebook từ chối xóa thì ghi vào job.data["refused"] (bài VẪN còn trên Facebook). Facebook giới hạn tần suất (code 4...)
    thì dừng ngay, các bài chưa xử lý giữ nguyên trong app và ghi job.data["rate_limited"] (giờ) cùng job.data["left"] (số bài còn lại).
    """
    from . import library
    job.set_progress(0, len(rels))
    deleted = gone = local = 0
    refused: list[str] = []
    failed: list[str] = []
    net_fails = 0
    stopped = False
    limited = left = limited_min = 0
    local_stop = False
    gone_streak = gone_stop = gone_left = 0
    for i, rel in enumerate(rels, 1):
        if job.cancelled:
            job.log("Đã dừng theo yêu cầu.")
            stopped = True
            break
        name = rel.rsplit("/", 1)[-1]
        try:
            folder = library.resolve(rel)
            sched = commenter.read_sched(folder)
            page = pages.resolve(sched) if sched else None
            if page is None or page["id"] != page_id:
                raise ManageError("Video này không thuộc Fanpage đang chọn, hoặc chưa được hẹn giờ.")
            res = _cancel(folder, local_only)
            net_fails = 0
            deleted += res == "deleted"
            gone += res == "gone"
            local += res == "local"
            gone_streak = gone_streak + 1 if res == "gone" else 0
            job.log(f"Đã huỷ lịch: {name}" + (f" (Facebook báo không còn bài; {getattr(res, 'detail', '')[:220]})" if res == "gone" else ""))
            if gone_streak >= MAX_GONE_STREAK:
                # Bài bị xóa thật thì hiếm khi dồn thành chuỗi; chuỗi "không còn" thường là Facebook đang lỗi. Dừng để người dùng đối chiếu.
                gone_stop, gone_left = gone_streak, len(rels) - i
                job.log(f"Dừng: {gone_streak} bài liên tiếp Facebook báo không còn. Nếu bài thật sự còn trên Facebook thì chúng vẫn sẽ được đăng. "
                        f"Mở Meta Business Suite (Nội dung đã lên lịch) kiểm tra {gone_streak} bài vừa rồi; {gone_left} bài chưa xử lý vẫn giữ nguyên trong app.")
                stopped = True
                break
            if PACE_SECONDS:
                job.cancel_event.wait(PACE_SECONDS)
        except RateLimited as exc:
            limited, left = exc.hours, len(rels) - i + 1   # bài này và mọi bài sau nó chưa được xử lý
            limited_min, local_stop = exc.minutes, exc.local
            job.log(f"{name}: {exc}")
            if exc.local:
                job.log(f"App tự dừng để không chạm giới hạn lượt gọi của Facebook: {left} bài chưa huỷ vẫn giữ nguyên trong app. Thử lại sau khoảng {limited_min} phút.")
            else:
                job.log(f"Facebook đang giới hạn: dừng ngay, {left} bài chưa huỷ vẫn giữ nguyên trong app. Thử lại sau khoảng {limited_min} phút.")
            if exc.page_block:   # Facebook chặn riêng Page này: nhắc ở Tổng quan, chặn hẹn giờ thêm cho tới khi hết
                pages.mark_blocked(page_id, limited, str(exc))
            stopped = True
            break
        except ManageError as exc:
            if exc.refused:
                refused.append(rel)
                net_fails = 0
                job.log(f"Facebook không cho xóa: {name}: {exc}")
            else:
                failed.append(rel)
                net_fails = net_fails + 1 if "kết nối" in str(exc) else 0
                job.log(f"Không huỷ được: {name}: {exc}")
        except ValueError as exc:
            failed.append(rel)
            job.log(f"Không huỷ được: {name}: {exc}")
        job.set_progress(i, len(rels))
        if net_fails >= MAX_NET_FAILS:
            job.log("Dừng vì nhiều lần liên tiếp không kết nối được Facebook. Kiểm tra mạng rồi thử lại.")
            stopped = True
            break
    job.data = {"refused": refused, "failed": failed, "rate_limited": limited, "rate_limited_minutes": limited_min,
                "app_limited": local_stop, "left": left, "done": deleted + gone + local,
                "gone": gone, "gone_stop": gone_stop, "gone_left": gone_left}
    done = deleted + gone + local
    parts = [f"Đã huỷ lịch {done}/{len(rels)} bài"]
    if gone:
        parts.append(f"{gone} bài Facebook báo không còn")
    if gone_stop:
        parts.append(f"đã dừng vì {gone_stop} bài liên tiếp Facebook báo \"không còn\" (bất thường, nên kiểm tra trong Meta Business Suite), còn {gone_left} bài chưa xử lý")
    if limited and local_stop:
        parts.append(f"app tự dừng để không chạm giới hạn lượt gọi Facebook, còn {left} bài chưa huỷ (vẫn nằm trong Chờ đăng, thử lại sau khoảng {limited_min} phút)")
    elif limited:
        parts.append(f"Facebook đang giới hạn lượt gọi API nên đã dừng, còn {left} bài chưa huỷ (vẫn nằm trong Chờ đăng, thử lại sau khoảng {limited_min} phút)")
    if refused:
        parts.append(f"{len(refused)} bài Facebook không cho xóa qua API (các bài này VẪN còn trên Facebook)")
    if failed:
        parts.append(f"{len(failed)} bài lỗi (xem nhật ký)")
    if stopped and not limited and not gone_stop:
        parts.append("đã dừng giữa chừng")
    return ", ".join(parts) + "."


def parse_when(page: dict, text: str) -> datetime:
    """"YYYY-MM-DD HH:MM" theo múi giờ của Page. Phải cách hiện tại >= 15 phút và <= 29 ngày."""
    try:
        tz = pages.tz_of(page)
        when = datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
    except (TypeError, ValueError) as exc:
        raise ManageError("Giờ mới không hợp lệ.") from exc
    now = datetime.now(tz)
    if when < now + timedelta(minutes=15):
        raise ManageError("Giờ mới phải cách hiện tại ít nhất khoảng 15 phút.")
    if when > now + timedelta(days=29):
        raise ManageError("Facebook chỉ cho hẹn giờ trong vòng 29 ngày tới.")
    return when


def retime(folder: Path, when_text: str) -> str:
    """Sửa trực tiếp giờ hẹn trên Facebook. Ném ManageError(refused=True) nếu Facebook không cho."""
    sched, page = _load(folder)
    when = parse_when(page, when_text)
    _check_not_published(folder, sched, page)
    vid = sched.get("video_id")
    if not vid:
        raise ManageError("Bản ghi hẹn giờ thiếu video ID, không đổi giờ được.")
    fb_retime(page, vid, int(when.timestamp()))
    with commenter._lock:
        sched = commenter.read_sched(folder)
        sched["scheduled_for"] = when.isoformat()
        sched["retimed_at"] = datetime.now(timezone.utc).isoformat()
        sched["publish_status"] = "scheduled"
        sched.pop("publish_detail", None)
        for k in ("comment_status", "comment_next_try"):
            sched.pop(k, None)
        sched["comment_attempts"] = 0
        commenter.write_sched(folder, sched)
    return f"Đã đổi giờ đăng sang {when:%H:%M %d/%m/%Y} ({pages.tz_of(page)})."
