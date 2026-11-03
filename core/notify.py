"""Gửi thông báo khi có sự cố: thông báo macOS và/hoặc tin nhắn Telegram.

Cấu hình (Cài đặt chung > Thông báo, lưu trong .env):
  NOTIFY_MAC          1 = bật thông báo macOS (mặc định bật, chỉ có tác dụng trên macOS)
  TELEGRAM_BOT_TOKEN  token của bot (tạo bằng @BotFather)
  TELEGRAM_CHAT_ID    ID cuộc trò chuyện nhận tin

Mỗi sự cố có một khóa chống lặp (key): cùng khóa thì không gửi lại trong `ttl_hours` giờ, để không bị làm phiền.
Việc gửi chạy ở luồng nền nên không làm chậm tác vụ đang chạy; mọi lỗi khi gửi chỉ được ghi lại, không ném ra ngoài.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone

import requests

from . import config

STATE_FILE = config.ROOT / "notify_state.json"
_lock = threading.Lock()
ASYNC = True            # tests đặt False để gửi tuần tự
last_error = ""         # lỗi gần nhất khi gửi (hiện ở nút Gửi thử)


def mac_enabled() -> bool:
    return sys.platform == "darwin" and config.get("NOTIFY_MAC", "1") not in ("0", "false", "off", "no") and bool(shutil.which("osascript"))


def telegram_configured() -> bool:
    return bool(config.get("TELEGRAM_BOT_TOKEN") and config.get("TELEGRAM_CHAT_ID"))


def configured() -> bool:
    return mac_enabled() or telegram_configured()


def _load() -> dict:
    try:
        d = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (ValueError, OSError):
        return {}


def _due(key: str, ttl_hours: float, now: datetime) -> bool:
    """Ghi nhận đã gửi `key` và trả True nếu chưa gửi trong `ttl_hours` giờ qua."""
    with _lock:
        state = _load()
        try:
            prev = datetime.fromisoformat(state.get(key, ""))
        except (TypeError, ValueError):
            prev = None
        if prev is not None and now - prev < timedelta(hours=ttl_hours):
            return False
        state[key] = now.isoformat()
        cutoff = now - timedelta(days=14)   # dọn khóa cũ
        for k in list(state):
            try:
                if datetime.fromisoformat(state[k]) < cutoff:
                    del state[k]
            except (TypeError, ValueError):
                del state[k]
        try:
            STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
        return True


def _forget(key: str) -> None:
    """Bỏ dấu đã gửi của `key` (khi gửi thất bại ở mọi kênh) để lần sau còn thử lại, không phải chờ hết thời hạn chống lặp."""
    with _lock:
        state = _load()
        if state.pop(key, None) is not None:
            try:
                STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            except OSError:
                pass


def send_mac(title: str, body: str) -> str:
    """Trả về "" nếu gửi được, ngược lại là lý do."""
    if sys.platform != "darwin" or not shutil.which("osascript"):
        return "Chỉ có trên macOS."
    script = ["on run argv", "display notification (item 2 of argv) with title (item 1 of argv)", "end run"]
    cmd = ["osascript"]
    for line in script:
        cmd += ["-e", line]
    try:
        r = subprocess.run(cmd + [title[:120], body[:500]], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"Không chạy được osascript ({type(exc).__name__})."
    return "" if r.returncode == 0 else (r.stderr or "osascript báo lỗi").strip()[:200]


def send_telegram(text: str) -> str:
    token, chat = config.get("TELEGRAM_BOT_TOKEN"), config.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return "Chưa điền token bot hoặc chat ID."
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text[:3500], "disable_web_page_preview": True},
            timeout=15,
        )
        data = r.json()
    except (requests.RequestException, ValueError) as exc:
        return config.redact(f"Không gửi được tới Telegram ({type(exc).__name__}).")
    if r.status_code == 200 and data.get("ok"):
        return ""
    return config.redact(f"Telegram báo lỗi: {data.get('description', r.status_code)}")[:300]


def deliver(title: str, body: str) -> dict:
    """Gửi ngay tới mọi kênh đã cấu hình. Trả về {kênh: "" (ok) hoặc lý do}."""
    global last_error
    res = {}
    if mac_enabled():
        res["mac"] = send_mac(title, body)
    if telegram_configured():
        res["telegram"] = send_telegram(f"{title}\n{body}")
    bad = [f"{k}: {v}" for k, v in res.items() if v]
    last_error = "; ".join(bad)
    return res


def send(title: str, body: str, key: str = "", ttl_hours: float = 6) -> bool:
    """Gửi thông báo sự cố. key rỗng = luôn gửi. Trả về True nếu đã đưa vào hàng gửi."""
    try:
        if not configured():
            return False
        if key and not _due(key, ttl_hours, datetime.now(timezone.utc)):
            return False
        if ASYNC:
            threading.Thread(target=_safe_deliver, args=(title, body, key), daemon=True).start()
        else:
            _safe_deliver(title, body, key)
        return True
    except Exception:  # noqa: BLE001  thông báo không bao giờ được làm hỏng tác vụ chính
        return False


def _safe_deliver(title: str, body: str, key: str = "") -> None:
    try:
        res = deliver(title, body)
        if key and res and all(res.values()):   # mọi kênh đều lỗi: cho phép thử lại ở lần kiểm tra sau
            _forget(key)
    except Exception:  # noqa: BLE001
        if key:
            _forget(key)


def telegram_find_chat() -> dict:
    """Tìm chat ID từ tin nhắn mới nhất gửi cho bot (người dùng nhắn bot một tin trước). {"chat_id", "name"} hoặc {"error"}."""
    token = config.get("TELEGRAM_BOT_TOKEN")
    if not token:
        return {"error": "Chưa điền token bot."}
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=15)
        data = r.json()
    except (requests.RequestException, ValueError) as exc:
        return {"error": config.redact(f"Không kết nối được Telegram ({type(exc).__name__}).")}
    if not data.get("ok"):
        return {"error": config.redact(f"Telegram báo lỗi: {data.get('description', r.status_code)}")}
    for upd in reversed(data.get("result") or []):
        msg = upd.get("message") or upd.get("channel_post") or upd.get("my_chat_member") or {}
        chat = msg.get("chat") or {}
        if chat.get("id") is not None:
            name = chat.get("title") or " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x) or chat.get("username") or ""
            return {"chat_id": str(chat["id"]), "name": name}
    return {"error": "Chưa thấy tin nhắn nào gửi cho bot. Hãy mở bot trong Telegram, bấm Start hoặc nhắn một tin, rồi thử lại."}
