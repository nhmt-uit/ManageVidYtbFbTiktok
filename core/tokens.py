"""Token Facebook. User token nằm trong .env, Page token nằm trong pages.json. Không bao giờ trả về giao diện."""
from __future__ import annotations

import time
from datetime import datetime, timezone

import requests

from . import config, fbgate, pages


def _get(url: str, params: dict, step: str, cls: str = "user") -> dict:
    try:
        r = fbgate.request("get", url, cls=cls, params=params, timeout=60)
    except fbgate.RateLimited as exc:
        raise RuntimeError(f"{step}: {exc}") from None
    except requests.RequestException as exc:
        # Không đưa nội dung lỗi gốc vào thông báo: nó thường chứa cả URL kèm token
        raise RuntimeError(f"{step}: không kết nối được Facebook ({type(exc).__name__})") from None
    try:
        data = r.json()
    except ValueError:
        raise RuntimeError(f"{step}: phản hồi không phải JSON ({r.status_code})")
    if r.status_code >= 400 or "error" in data:
        err = data.get("error", {})
        raise RuntimeError(f"{step}: {err.get('message', data)} (code {err.get('code')})")
    return data


def _long_lived_user_token() -> str:
    user_token = config.get("FB_USER_TOKEN")
    app_id = config.get("FB_APP_ID")
    app_secret = config.get("FB_APP_SECRET")
    if not (user_token and app_id and app_secret):
        raise RuntimeError("Cần điền App ID, App Secret và User token trong Cài đặt > Token FB.")
    ll = _get(
        f"{config.graph_url()}/oauth/access_token",
        {
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": user_token,
        },
        "Đổi token dài hạn",
    )
    return ll["access_token"]


def discover() -> dict:
    """User token -> danh sách mọi Page bạn quản lý. Page đã có trong app được cập nhật token mới."""
    try:
        ll = _long_lived_user_token()
        accounts = _get(
            f"{config.graph_url()}/me/accounts", {"access_token": ll, "limit": 100}, "Lấy danh sách Page"
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": str(exc), "candidates": []}
    found = [p for p in accounts.get("data", []) if p.get("id") and p.get("access_token")]
    if not found:
        return {
            "ok": False,
            "message": "Danh sách Page trống. Lấy lại User token và chọn các Fanpage ở cửa sổ cấp quyền.",
            "candidates": [],
        }
    res = pages.set_candidates(found)
    msg = f"Tìm thấy {len(found)} Page."
    if res["refreshed"]:
        msg += f" Đã làm mới token của {res['refreshed']} Page đã có trong app."
    return {"ok": True, "message": msg, "candidates": res["candidates"]}


_name_tried: dict = {}   # Page ID -> lần thử gần nhất (không hỏi lại liên tục khi mất mạng hoặc token hỏng)


def fill_names() -> None:
    """Page chưa biết tên trên Facebook (ví dụ Page chuyển từ bản cũ): hỏi Facebook rồi lưu lại."""
    now = time.time()
    for p in pages.all_pages():
        if p.get("fb_name") or not p.get("token"):
            continue
        if now - _name_tried.get(p["id"], 0) < 600:
            continue
        _name_tried[p["id"]] = now
        try:
            me = _get(f"{config.graph_url()}/me", {"access_token": p["token"], "fields": "id,name"}, "Lấy tên Page", cls="poll")
            pages.set_fb_name(p["id"], me.get("name", ""))
        except Exception:  # noqa: BLE001
            pass  # không có mạng hoặc token hỏng: dùng tên tạm, lần sau thử lại


def _scopes_note(scopes: list, page: dict) -> list[str]:
    lines = []
    if scopes:
        lines.append("Quyền: " + ", ".join(scopes) + ".")
        need = ["pages_manage_posts", "publish_video"]
        if page.get("auto_comment"):
            need.append("pages_manage_engagement")
        for n in need:
            if n not in scopes:
                lines.append(f"Thiếu quyền: {n}.")
    return lines


def check_page(page_id: str) -> dict:
    page = pages.get(page_id)
    if page is None:
        return {"ok": False, "message": "Không tìm thấy Fanpage."}
    page_token = page.get("token")
    if not page_token:
        return {"ok": False, "message": "Page này chưa có Page token."}
    graph = config.graph_url()
    try:
        me = _get(f"{graph}/me", {"access_token": page_token, "fields": "id,name"}, "Kiểm tra token")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"Token không dùng được: {exc}"}

    lines = [f"Token hợp lệ. Page: {me.get('name')} (id {me.get('id')})."]
    app_id, app_secret = config.get("FB_APP_ID"), config.get("FB_APP_SECRET")
    if app_id and app_secret:
        try:
            dbg = _get(
                f"{graph}/debug_token",
                {"input_token": page_token, "access_token": f"{app_id}|{app_secret}"},
                "debug_token",
            )["data"]
            exp = dbg.get("expires_at", 0)
            if exp:
                when = datetime.fromtimestamp(exp, tz=timezone.utc).astimezone()
                lines.append(f"Hết hạn: {when:%Y-%m-%d %H:%M}.")
            else:
                lines.append("Hết hạn: không (Never).")
            lines += _scopes_note(dbg.get("scopes", []), page)
        except Exception as exc:  # noqa: BLE001
            lines.append(f"Không đọc được hạn token: {exc}")
    return {"ok": True, "message": " ".join(lines)}


def check_user() -> dict:
    """Kiểm tra User token đang lưu trong .env (App ID + App Secret)."""
    token, app_id, app_secret = config.get("FB_USER_TOKEN"), config.get("FB_APP_ID"), config.get("FB_APP_SECRET")
    if not (token and app_id and app_secret):
        return {"ok": False, "message": "Cần điền App ID, App Secret và User token."}
    try:
        dbg = _get(
            f"{config.graph_url()}/debug_token",
            {"input_token": token, "access_token": f"{app_id}|{app_secret}"},
            "debug_token",
        )["data"]
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": str(exc)}
    if not dbg.get("is_valid"):
        return {"ok": False, "message": "User token không còn hợp lệ hoặc đã hết hạn. Lấy token mới ở Graph API Explorer."}
    exp = dbg.get("expires_at", 0)
    when = datetime.fromtimestamp(exp, tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M") if exp else "không"
    scopes = ", ".join(dbg.get("scopes", []))
    return {"ok": True, "message": f"User token hợp lệ. Hết hạn: {when}. Quyền: {scopes}."}
