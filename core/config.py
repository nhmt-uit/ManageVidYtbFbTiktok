"""Cấu hình lưu trong .env (không cần thư viện ngoài)."""
from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"

# Khóa bí mật: không bao giờ trả về giao diện, không in ra log
SECRET_KEYS = {"FB_APP_SECRET", "FB_USER_TOKEN", "TELEGRAM_BOT_TOKEN", "TRANSLATE_API_KEY"}
# Các khóa cho phép sửa từ giao diện
EDITABLE_KEYS = [
    "OUTPUT_DIR",
    "DOWNLOAD_MAX_HEIGHT",
    "DOWNLOAD_SLEEP_MIN",
    "DOWNLOAD_SLEEP_MAX",
    "YTDLP_COOKIES_BROWSER",
    "REDNOTE_COOKIES_BROWSER",
    "SCHEDULE_TZ",
    "SCHEDULE_INTERVAL_HOURS",
    "FB_APP_ID",
    "FB_APP_SECRET",
    "FB_USER_TOKEN",
    "FB_API_VERSION",
    "COMMENT_DELAY_MINUTES",
    "COMMENT_GAP_SECONDS",
    "PUBLISH_LIMIT_24H",
    "SCHEDULE_DELAY_SECONDS",
    "FB_CALLS_PER_HOUR",
    "REELS_CHECK",
    "YTDLP_AUTO_UPDATE",
    "LOW_STOCK_DAYS",
    "NOTIFY_MAC",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TRANSLATE_PROVIDER",
    "TRANSLATE_API_KEY",
    "TRANSLATE_MODEL",
    "TRANSLATE_BASE_URL",
]
COMMENT_DEFAULT_FILE = ROOT / "comment_default.txt"  # bản cũ, chỉ để nâng cấp lên pages.json
COMMENT_POOL_FILE = ROOT / "comment_pool.json"      # bản cũ, chỉ để nâng cấp lên pages.json
DEFAULTS = {
    "COMMENT_DELAY_MINUTES": "3",
    "COMMENT_GAP_SECONDS": "30",
    "DOWNLOAD_MAX_HEIGHT": "1080",
    "DOWNLOAD_SLEEP_MIN": "3",
    "DOWNLOAD_SLEEP_MAX": "8",
    "SCHEDULE_TZ": "Asia/Tokyo",
    "SCHEDULE_INTERVAL_HOURS": "6",
    "FB_API_VERSION": "v21.0",
    "PUBLISH_LIMIT_24H": "30",
    "SCHEDULE_DELAY_SECONDS": "15",
    "FB_CALLS_PER_HOUR": "150",
    "FB_MIN_INTERVAL_SECONDS": "0.6",
    "REELS_CHECK": "1",
    "YTDLP_AUTO_UPDATE": "1",
    "LOW_STOCK_DAYS": "3",
    "NOTIFY_MAC": "1",
    "TRANSLATE_PROVIDER": "claude-code",
}


def get_int(key: str, default: int, lo: int, hi: int) -> int:
    """Đọc cài đặt dạng số nguyên, sai hoặc ngoài khoảng thì dùng giá trị mặc định / chặn về biên."""
    try:
        v = int(float(get(key) or default))
    except (TypeError, ValueError, OverflowError):
        v = default
    return min(max(v, lo), hi)


def _parse_line(line: str):
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        return None
    key, _, value = line.partition("=")
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return key.strip(), value


def load_env(path: Path = ENV_FILE) -> None:
    """Nạp .env vào os.environ. Biến có sẵn trong shell được ưu tiên."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_line(line)
        if parsed and parsed[0] not in os.environ:
            os.environ[parsed[0]] = parsed[1]


def bad_value(value) -> bool:
    """Giá trị không được ghi vào .env: có xuống dòng/ký tự điều khiển (làm hỏng hoặc chèn thêm dòng) hoặc dấu nháy kép."""
    text = str(value)
    return '"' in text or any(ord(c) < 32 or ord(c) == 127 for c in text)


def update_env(updates: dict, path: Path = ENV_FILE) -> None:
    """Cập nhật hoặc thêm khóa trong .env, giữ nguyên các dòng khác."""
    for k, v in updates.items():
        if bad_value(v):
            raise ValueError(f"Giá trị của {k} có ký tự không hợp lệ (xuống dòng, ký tự điều khiển hoặc dấu \").")
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = {k: str(v) for k, v in updates.items()}
    out = []
    for line in lines:
        parsed = _parse_line(line)
        if parsed and parsed[0] in remaining:
            out.append(f'{parsed[0]}="{remaining.pop(parsed[0])}"')
        else:
            out.append(line)
    for key, value in remaining.items():
        out.append(f'{key}="{value}"')
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)  # chỉ chủ sở hữu đọc được
    except OSError:
        pass
    for key, value in updates.items():
        os.environ[key] = str(value)


_SECRET_PARAM_RE = re.compile(r"(access_token|client_secret|fb_exchange_token|input_token)=[^&\s'\")]+", re.IGNORECASE)


_BOT_TOKEN_RE = re.compile(r"/bot\d+:[A-Za-z0-9_-]+")


def redact(text) -> str:
    """Che token/secret nếu lỡ nằm trong thông báo lỗi (ví dụ URL trong lỗi kết nối)."""
    return _BOT_TOKEN_RE.sub("/bot***", _SECRET_PARAM_RE.sub(lambda m: m.group(1) + "=***", str(text)))


def get(key: str, default: str = "") -> str:
    value = os.environ.get(key)
    if value:
        return value
    return DEFAULTS.get(key, default)


def output_dir() -> Path:
    default = Path.home() / "Documents" / "My_Project" / "MakingVideo" / "OfflineYtb"
    return Path(os.environ.get("OUTPUT_DIR") or default).expanduser()


def graph_url() -> str:
    return f"https://graph.facebook.com/{get('FB_API_VERSION')}"


def public_settings() -> dict:
    """Giá trị hiển thị trên giao diện. Khóa bí mật chỉ cho biết đã có hay chưa."""
    values, secrets = {}, {}
    for key in EDITABLE_KEYS:
        if key in SECRET_KEYS:
            secrets[key] = bool(os.environ.get(key))
        elif key == "OUTPUT_DIR":
            values[key] = str(output_dir())
        else:
            values[key] = get(key)
    return {"values": values, "secrets": secrets}
