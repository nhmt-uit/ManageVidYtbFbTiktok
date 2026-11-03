"""Danh sách Fanpage, lưu trong pages.json (quyền 600, đã gitignore).

Mỗi Page: id, name (tên gọi trong app), fb_name (tên trên Facebook), token (Page token),
auto_comment (bật/tắt tự động comment cho Page này) và comments (kho comment của Page).
Token không bao giờ được trả về giao diện, xem public().
"""
from __future__ import annotations

import json
import os
import random
import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import config

PAGES_FILE = config.ROOT / "pages.json"
COMMENT_MAX = 2000
POOL_MAX_ITEMS = 50

DEFAULT_TZ = "Asia/Ho_Chi_Minh"
# Cài đặt riêng của từng Page: (nhỏ nhất, lớn nhất, khóa cài đặt chung dùng khi Page không đặt, giá trị mặc định)
SETTING_FIELDS = {
    "publish_limit_24h": (0, 1000, "PUBLISH_LIMIT_24H", 30),
    "delay_seconds": (0, 600, "SCHEDULE_DELAY_SECONDS", 15),
    "comment_delay_minutes": (0, 1440, "COMMENT_DELAY_MINUTES", 3),
    "comment_gap_seconds": (0, 3600, "COMMENT_GAP_SECONDS", 30),
}

_lock = threading.RLock()
_candidates: dict[str, dict] = {}   # Page tìm thấy từ Facebook, chưa thêm (chỉ giữ trong bộ nhớ)
_last_used: dict[str, str] = {}     # comment vừa dùng gần nhất của từng Page (tránh lặp liên tiếp)


def _clean_items(items) -> list[str]:
    out = []
    for x in items or []:
        t = str(x).strip()[:COMMENT_MAX]
        if t and t != "-" and t not in out:
            out.append(t)
    return out[:POOL_MAX_ITEMS]


def _legacy_pool() -> list[str]:
    for f in (config.COMMENT_POOL_FILE, config.COMMENT_DEFAULT_FILE):
        if not f.exists():
            continue
        try:
            raw = f.read_text(encoding="utf-8")
            if f.suffix == ".json":
                return _clean_items(json.loads(raw))
            return _clean_items([raw])
        except (ValueError, OSError, TypeError):
            continue
    return []


def _migrate() -> dict:
    """Bản cũ chỉ có một Page trong .env (FB_PAGE_ID / FB_PAGE_TOKEN): chuyển thành Page đầu tiên."""
    data = {"legacy_page_id": "", "pages": []}
    pid, tok = os.environ.get("FB_PAGE_ID", ""), os.environ.get("FB_PAGE_TOKEN", "")
    if pid and tok:
        data["legacy_page_id"] = pid
        data["pages"].append({
            "id": pid,
            "name": "",
            "fb_name": "",
            "token": tok,
            "auto_comment": os.environ.get("AUTO_COMMENT", "0") == "1",
            "comments": _legacy_pool(),
            "added_at": datetime.now().isoformat(timespec="seconds"),
        })
    _write(data)
    if data["pages"]:
        try:
            config.update_env({"FB_PAGE_ID": "", "FB_PAGE_TOKEN": ""})  # token đã chuyển sang pages.json
        except OSError:
            pass
        if config.COMMENT_POOL_FILE.exists():
            try:
                config.COMMENT_POOL_FILE.rename(config.COMMENT_POOL_FILE.with_name("comment_pool.migrated.json"))
            except OSError:
                pass
    return data


def _write(data: dict) -> None:
    tmp = PAGES_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        tmp.chmod(0o600)
    except OSError:
        pass
    tmp.replace(PAGES_FILE)


def load() -> dict:
    with _lock:
        if not PAGES_FILE.exists():
            return _migrate()
        try:
            data = json.loads(PAGES_FILE.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            data = {}
        data.setdefault("legacy_page_id", "")
        if not isinstance(data.get("pages"), list):
            data["pages"] = []
        return data


def all_pages() -> list[dict]:
    return load()["pages"]


def get(page_id: str):
    for p in all_pages():
        if p["id"] == page_id:
            return p
    return None


def label(p: dict) -> str:
    """Tên hiển thị: tên bạn tự đặt, nếu chưa đặt thì "Tên Fanpage - Fanpage ID"."""
    custom = (p.get("name") or "").strip()
    if custom and custom != f"Fanpage {p['id']}":   # "Fanpage <id>" là tên tạm của bản cũ
        return custom
    return f"{p.get('fb_name') or 'Fanpage'} - {p['id']}"


def resolve(sched: dict):
    """Page của một video đã hẹn giờ. Video cũ chưa ghi page_id thuộc về Page cũ duy nhất."""
    data = load()
    pid = (sched or {}).get("page_id") or data["legacy_page_id"]
    return next((p for p in data["pages"] if p["id"] == pid), None)


def page_label(sched: dict) -> str:
    p = resolve(sched)
    return label(p) if p else ((sched or {}).get("page_name") or "(Page đã xóa)")


DEFAULT_SCHEDULE = {"slots": [], "max_per_day": 5, "days_off": []}


def clean_settings(d) -> dict:
    """Cài đặt riêng của Page: chỉ giữ giá trị bạn đã đặt (ô để trống = dùng mặc định / cài đặt chung)."""
    d = d if isinstance(d, dict) else {}
    out: dict = {}
    tz = str(d.get("tz") or "").strip()
    if tz:
        try:
            ZoneInfo(tz)
        except Exception:  # noqa: BLE001
            raise ValueError(f'Múi giờ "{tz}" không hợp lệ. Ví dụ: Asia/Ho_Chi_Minh.') from None
        out["tz"] = tz
    for key, (lo, hi, _, _) in SETTING_FIELDS.items():
        raw = d.get(key)
        if raw is None or str(raw).strip() == "":
            continue
        try:
            v = int(float(raw))
        except (TypeError, ValueError, OverflowError):
            raise ValueError(f"Giá trị {key} không hợp lệ.") from None
        if not lo <= v <= hi:
            raise ValueError(f"Giá trị {key} phải từ {lo} đến {hi}.")
        out[key] = v
    return out


def settings_of(p: dict) -> dict:
    try:
        return clean_settings(p.get("settings") or {})
    except ValueError:
        return {}


def effective(p: dict) -> dict:
    """Cài đặt đang áp dụng cho Page: giá trị riêng nếu có, không thì cài đặt chung, không thì mặc định."""
    own = settings_of(p)
    out = {"tz": own.get("tz") or DEFAULT_TZ}
    for key, (lo, hi, cfg_key, default) in SETTING_FIELDS.items():
        out[key] = own[key] if key in own else config.get_int(cfg_key, default, lo, hi)
    return out


def tz_of(p: dict) -> ZoneInfo:
    return ZoneInfo(effective(p)["tz"])


def set_settings(page_id: str, settings: dict) -> dict:
    return _mutate(page_id, lambda p: p.__setitem__("settings", settings))


def set_schedule(page_id: str, rules: dict) -> dict:
    return _mutate(page_id, lambda p: p.__setitem__("schedule", rules))


def blocked_until(p: dict):
    """Thời điểm Facebook hết giới hạn tần suất của Page (None nếu không bị chặn hoặc đã qua)."""
    try:
        t = datetime.fromisoformat(p.get("blocked_until") or "")
    except (TypeError, ValueError):
        return None
    if t.tzinfo is None:
        t = t.astimezone()
    return t if t > datetime.now(timezone.utc) else None


def mark_blocked(page_id: str, hours: float, reason: str) -> None:
    def fn(p):
        until = datetime.now(timezone.utc) + timedelta(hours=hours)
        cur = blocked_until(p)
        if cur and cur > until:
            until = cur
        p["blocked_until"] = until.isoformat()
        p["blocked_reason"] = config.redact(reason)[:300]
    try:
        p = _mutate(page_id, fn)
    except KeyError:
        return
    try:   # báo cho người dùng biết (chống lặp 6 giờ); lỗi khi gửi không ảnh hưởng gì
        from . import notify
        until = blocked_until(p)
        when = f" đến khoảng {until.astimezone(tz_of(p)):%H:%M %d/%m}" if until else ""
        notify.send(
            f"Facebook giới hạn tần suất: {label(p)}",
            f"Page này đang bị Facebook giới hạn tần suất{when}. App đã tạm dừng hẹn giờ và comment cho Page này, không cần làm gì thêm.",
            key=f"blocked:{page_id}", ttl_hours=6,
        )
    except Exception:  # noqa: BLE001
        pass


def clear_blocked(page_id: str) -> dict:
    def fn(p):
        p.pop("blocked_until", None)
        p.pop("blocked_reason", None)
    return _mutate(page_id, fn)


def _safe_rules(p: dict) -> dict:
    from . import planner   # nhập muộn để tránh vòng lặp import (planner dùng pages)
    return planner.rules_of(p)


def public(p: dict) -> dict:
    return {
        "schedule": _safe_rules(p),
        "settings": settings_of(p),
        "effective": effective(p),
        "blocked_until": (blocked_until(p).isoformat() if blocked_until(p) else ""),
        "blocked_reason": p.get("blocked_reason", "") if blocked_until(p) else "",
        "id": p["id"],
        "name": label(p),
        "fb_name": p.get("fb_name", ""),
        "has_token": bool(p.get("token")),
        "auto_comment": bool(p.get("auto_comment")),
        "comment_count": len(p.get("comments", [])),
    }


def _mutate(page_id: str, fn) -> dict:
    with _lock:
        data = load()
        for p in data["pages"]:
            if p["id"] == page_id:
                fn(p)
                _write(data)
                return p
    raise KeyError(page_id)


def rename_or_toggle(page_id: str, name=None, auto_comment=None) -> dict:
    def fn(p):
        if name is not None:
            p["name"] = str(name).strip()[:80]   # để trống = quay về "Tên Fanpage - ID"
        if auto_comment is not None:
            p["auto_comment"] = bool(auto_comment)
    return _mutate(page_id, fn)


def set_fb_name(page_id: str, fb_name: str) -> None:
    if fb_name:
        _mutate(page_id, lambda p: p.__setitem__("fb_name", fb_name))


def remove(page_id: str) -> None:
    with _lock:
        data = load()
        before = len(data["pages"])
        data["pages"] = [p for p in data["pages"] if p["id"] != page_id]
        if len(data["pages"]) == before:
            raise KeyError(page_id)
        _write(data)


# ---------- Tìm Page từ Facebook ----------
def set_candidates(found: list[dict]) -> dict:
    """found: [{id, name, access_token}]. Cập nhật token Page đã có, trả về danh sách có thể thêm."""
    with _lock:
        _candidates.clear()
        data = load()
        known = {p["id"]: p for p in data["pages"]}
        refreshed = 0
        for f in found:
            if f["id"] in known:
                known[f["id"]]["token"] = f["access_token"]
                known[f["id"]]["fb_name"] = f.get("name", known[f["id"]].get("fb_name", ""))
                refreshed += 1
            else:
                _candidates[f["id"]] = {"id": f["id"], "name": f.get("name", ""), "token": f["access_token"]}
        if refreshed:
            _write(data)
    return {
        "candidates": [{"id": c["id"], "name": c["name"]} for c in _candidates.values()],
        "refreshed": refreshed,
    }


def add_candidates(ids: list[str]) -> list[str]:
    added = []
    with _lock:
        data = load()
        for pid in ids:
            c = _candidates.get(pid)
            if not c or any(p["id"] == pid for p in data["pages"]):
                continue
            data["pages"].append({
                "id": pid,
                "name": "",
                "fb_name": c["name"],
                "token": c["token"],
                "auto_comment": False,
                "comments": [],
                "added_at": datetime.now().isoformat(timespec="seconds"),
            })
            added.append(pid)
            _candidates.pop(pid, None)
        if added:
            _write(data)
    return added


# ---------- Kho comment theo Page ----------
def read_pool(page_id: str) -> list[str]:
    p = get(page_id)
    return list(p.get("comments", [])) if p else []


def save_pool(page_id: str, items) -> list[str]:
    clean = _clean_items(items)
    _mutate(page_id, lambda p: p.__setitem__("comments", clean))
    return clean


def pick_random(page_id: str, items=None) -> str:
    """Chọn ngẫu nhiên một comment (mặc định trong kho của Page), tránh lặp lại câu vừa dùng nếu có từ 2 câu."""
    pool = read_pool(page_id) if items is None else list(items)
    if not pool:
        return ""
    choices = [c for c in pool if c != _last_used.get(page_id)] or pool
    pick = random.choice(choices)
    _last_used[page_id] = pick
    return pick
