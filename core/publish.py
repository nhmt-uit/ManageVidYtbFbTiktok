"""Hỏi Facebook xem một Reel đã hẹn giờ thực sự đã được đăng chưa.

Trạng thái lưu trong scheduled.json của video (do commenter.refresh_status ghi):
  publish_status: published | scheduled | processing | error | missing | unknown
  publish_detail: ghi chú lỗi hoặc lý do
  publish_checked_at, permalink

Lưu ý: cách Facebook trả trạng thái Reel có thể thay đổi, nên mọi trường được đọc theo kiểu "có thì dùng".
Nếu không hiểu được phản hồi thì trả về "unknown" và app xử lý như trước đây (không chặn comment).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests

from . import config, fbgate, ratelimit

FINAL_OK = "published"
BAD = ("error", "missing")        # cho phép "Hẹn lại"
NO_COMMENT = ("error", "missing")   # bài lỗi hoặc đã bị xóa khỏi Facebook thì không comment (hỏi lại định kỳ, hiện lại thì comment tiếp)
OVERDUE_MINUTES = 15


def _parse(iso):
    try:
        d = datetime.fromisoformat(iso)
        d = d if d.tzinfo else d.astimezone()
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    return d if 1971 <= d.year <= 2100 else None   # ngày vô lý (dữ liệu hỏng) không được làm sập phép cộng/trừ giờ ở nơi gọi


def _err_text(phase: dict) -> str:
    out = []
    for key in ("error", "errors"):
        e = (phase or {}).get(key)
        for item in e if isinstance(e, list) else ([e] if e else []):
            out.append(str(item.get("message", item)) if isinstance(item, dict) else str(item))
    return "; ".join(out)


def classify(data: dict) -> dict:
    """Phản hồi Graph API của một video -> {state, detail, permalink}.

    Theo tài liệu Reels Publishing API: status.video_status (error, expired, processing, ready, uploading,
    upload_failed, upload_complete) và ba giai đoạn uploading_phase, processing_phase, publishing_phase
    (status: completed, error, not_started, in_progress); publishing_phase.publish_status: draft, error,
    published, scheduled.
    """
    st = data.get("status") or {}
    if not isinstance(st, dict):
        st = {}
    vs = str(st.get("video_status") or "").lower()
    phases = {k: (st.get(k) if isinstance(st.get(k), dict) else {}) for k in ("uploading_phase", "processing_phase", "publishing_phase")}
    pstat = {k: str(v.get("status") or "").lower() for k, v in phases.items()}
    pub = phases["publishing_phase"]
    pub_status = str(pub.get("publish_status") or "").lower()
    link = data.get("permalink_url") or ""
    if link.startswith("/"):
        link = "https://www.facebook.com" + link

    if vs in ("error", "upload_failed", "expired") or "error" in pstat.values() or pub_status == "error":
        detail = "; ".join(t for t in (_err_text(v) for v in phases.values()) if t)
        return {"state": "error", "detail": detail or f"Facebook báo lỗi khi tải lên, xử lý hoặc đăng video ({vs or 'error'}).", "permalink": link}

    if data.get("published") is True or pub_status == "published":
        return {"state": "published", "detail": "", "permalink": link}
    if pub_status == "draft":
        return {"state": "error", "detail": "Facebook báo video đang ở dạng nháp, chưa được hẹn đăng.", "permalink": link}
    if pub_status == "scheduled" or data.get("published") is False:
        return {"state": "scheduled", "detail": "", "permalink": link}
    if vs in ("processing", "uploading", "upload_complete") or "in_progress" in pstat.values():
        return {"state": "processing", "detail": "", "permalink": link}
    return {"state": "unknown", "detail": "Không hiểu phản hồi trạng thái từ Facebook.", "permalink": link}


FIELD_SETS = ("status,published,permalink_url", "status")   # thử lần lượt nếu Facebook từ chối một trường


def _limited(exc: "fbgate.RateLimited") -> dict:
    return {"state": "unknown", "detail": str(exc), "permalink": "", "limited": True, "minutes": exc.minutes, "local": exc.local}


def fetch(page: dict, video_id: str, cls: str = "user") -> dict:
    """Hỏi Facebook trạng thái một video. Kết quả có "limited": True khi KHÔNG hỏi được vì app đang tự giới hạn lượt gọi
    hoặc Facebook đang báo giới hạn (khi đó không được hiểu là "không thấy bài")."""
    token = (page or {}).get("token")
    if not (token and video_id):
        return {"state": "unknown", "detail": "Thiếu Page token hoặc video ID.", "permalink": ""}
    data, r = {}, None
    for fields in FIELD_SETS:
        try:
            r = fbgate.request(
                "get",
                f"{config.graph_url()}/{video_id}",
                cls=cls,
                params={"fields": fields, "access_token": token},
                timeout=30,
            )
            data = r.json()
        except fbgate.RateLimited as exc:
            return _limited(exc)
        except (requests.RequestException, ValueError) as exc:
            return {"state": "unknown", "detail": f"Không kiểm tra được ({type(exc).__name__}).", "permalink": ""}
        err = data.get("error", {}) if isinstance(data, dict) else {}
        msg = str(err.get("message", ""))
        if err and err.get("code") == 100 and "field" in msg.lower():
            continue   # trường không hợp lệ: thử bộ trường nhỏ hơn thay vì coi là video không tồn tại
        break
    if r.status_code >= 400 or (isinstance(data, dict) and "error" in data):
        err = data.get("error", {}) if isinstance(data, dict) else {}
        msg = config.redact(f"{err.get('message', data)} (code {err.get('code')})")
        if err.get("code") in ratelimit.CALL_LIMIT_CODES:   # Facebook báo giới hạn lượt gọi: không phải "bài không tồn tại"
            return {"state": "unknown", "detail": "Facebook đang giới hạn lượt gọi API. " + msg, "permalink": "", "limited": True,
                    "minutes": max(fbgate.paused(), 1), "local": False}
        gone = err.get("code") == 803 or "does not exist" in str(err.get("message", "")).lower()
        if gone:
            return {
                "state": "missing",
                "detail": "Facebook không tìm thấy video này (có thể đã bị xóa, hoặc token thiếu quyền đọc). " + msg,
                "permalink": "",
            }
        return {"state": "unknown", "detail": msg, "permalink": ""}
    return classify(data)


def probe(page: dict, cls: str = "user") -> dict:
    """Kiểm tra chéo: token này có đọc được chính Page không (GET /{page_id}?fields=id)?

    Facebook trả đúng câu "Object ... does not exist" cho cả bài đã xóa lẫn khi nó đang lỗi hoặc token không đủ quyền.
    Nên trước khi tin "bài không còn" thì hỏi thử một thứ chắc chắn tồn tại: đọc được Page thì mới có cơ sở nói bài đã mất.
    Trả về {"ok": bool, "detail": str} (thêm "limited"/"minutes"/"local" khi bị giới hạn lượt gọi)."""
    token, pid = (page or {}).get("token"), (page or {}).get("id")
    if not (token and pid):
        return {"ok": False, "detail": "Thiếu Page token hoặc Page ID."}
    try:
        r = fbgate.request("get", f"{config.graph_url()}/{pid}", cls=cls, params={"fields": "id", "access_token": token}, timeout=30)
        data = r.json()
    except fbgate.RateLimited as exc:
        return {"ok": False, "detail": str(exc), "limited": True, "minutes": exc.minutes, "local": exc.local}
    except (requests.RequestException, ValueError) as exc:
        return {"ok": False, "detail": f"Không kiểm tra được ({type(exc).__name__})."}
    err = data.get("error", {}) if isinstance(data, dict) else {}
    if r.status_code >= 400 or err:
        msg = config.redact(f"{err.get('message', data)} (code {err.get('code')})")
        if err.get("code") in ratelimit.CALL_LIMIT_CODES:
            return {"ok": False, "detail": "Facebook đang giới hạn lượt gọi API. " + msg, "limited": True,
                    "minutes": max(fbgate.paused(), 1), "local": False}
        return {"ok": False, "detail": msg}
    return {"ok": bool(isinstance(data, dict) and data.get("id")), "detail": ""}


def apply(sched: dict, result: dict) -> None:
    sched["publish_status"] = result["state"]
    sched["publish_detail"] = result.get("detail", "")
    sched["publish_checked_at"] = datetime.now(timezone.utc).isoformat()
    if result.get("permalink"):
        sched["permalink"] = result["permalink"]


def due(sched: dict, now: datetime | None = None) -> bool:
    when = _parse(sched.get("scheduled_for"))
    now = now or datetime.now(timezone.utc)
    return bool(when and now >= when)


def overdue(sched: dict, now: datetime | None = None) -> bool:
    """Đã quá giờ hẹn một lúc mà Facebook vẫn báo chưa đăng."""
    when = _parse(sched.get("scheduled_for"))
    now = now or datetime.now(timezone.utc)
    return bool(
        when
        and now > when + timedelta(minutes=OVERDUE_MINUTES)
        and sched.get("publish_status") in ("scheduled", "processing")
    )


def fresh(sched: dict, seconds: int, now: datetime | None = None) -> bool:
    last = _parse(sched.get("publish_checked_at"))
    now = now or datetime.now(timezone.utc)
    return bool(last and now - last < timedelta(seconds=seconds))
