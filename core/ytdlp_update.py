"""Theo dõi và cập nhật yt-dlp.

YouTube hay đổi, nên yt-dlp bản cũ thường là nguyên nhân tải lỗi hàng loạt. Module này:
  - so phiên bản đang dùng với bản mới nhất trên PyPI,
  - cập nhật bằng pip vào đúng môi trường ảo của app (có kiểm tra lại, lỗi thì trả về bản cũ),
  - khi chạy nền bằng service.sh (launchd) và bật tự cập nhật: mỗi ngày kiểm tra một lần, cập nhật khi rảnh
    rồi tự khởi động lại app một lần để dùng bản mới (launchd bật lại ngay).
Chạy bằng ./run.sh thì chỉ cập nhật, việc khởi động lại do bạn làm (Ctrl+C rồi ./run.sh).

Trạng thái lưu trong ytdlp_state.json.
"""
from __future__ import annotations

import importlib.metadata
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone

import requests

from . import config

STATE_FILE = config.ROOT / "ytdlp_state.json"
PYPI_URL = "https://pypi.org/pypi/yt-dlp/json"
SERVICE_LABEL = "com.managevideos.app"
CHECK_EVERY = timedelta(hours=24)
RETRY_AFTER_FAIL = timedelta(hours=6)
STARTUP_GRACE = 120          # giây sau khi app khởi động mới bắt đầu kiểm tra, để không làm chậm lúc mở app
STALE_DAYS = 45              # yt-dlp cũ hơn số ngày này thì nhắc cập nhật khi tải lỗi
_t0 = time.time()
_lock = threading.Lock()     # chỉ một lần cập nhật tại một thời điểm


def auto_enabled() -> bool:
    return config.get("YTDLP_AUTO_UPDATE", "1") not in ("0", "false", "off", "no")


def in_service() -> bool:
    """Đang chạy dưới launchd do service.sh cài (launchd đặt XPC_SERVICE_NAME = nhãn dịch vụ)."""
    return os.environ.get("XPC_SERVICE_NAME") == SERVICE_LABEL


def loaded_version() -> str:
    try:
        from yt_dlp.version import __version__
        return str(__version__)
    except Exception:  # noqa: BLE001
        return ""


def installed_version() -> str:
    try:
        return importlib.metadata.version("yt-dlp")
    except importlib.metadata.PackageNotFoundError:
        return ""


def pending_restart() -> bool:
    """Bản cài trên đĩa khác bản đang chạy trong tiến trình này: cần khởi động lại app để dùng bản mới."""
    inst, cur = installed_version(), loaded_version()
    if not (inst and cur):
        return False
    return _key(inst) != _key(cur)   # so theo số: yt_dlp ghi "2026.11.03" còn metadata ghi "2026.11.3"


def _key(version: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", version)[:4])


def is_newer(latest: str, current: str) -> bool:
    try:
        a, b = _key(latest), _key(current)
    except ValueError:
        return False
    return bool(a) and bool(b) and a > b


def age_days(version: str, today: date | None = None) -> int | None:
    """yt-dlp đánh số phiên bản theo ngày phát hành (2026.10.26): trả về số ngày đã qua, hoặc None nếu không đọc được."""
    m = re.match(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", version or "")
    if not m:
        return None
    try:
        return ((today or date.today()) - date(int(m.group(1)), int(m.group(2)), int(m.group(3)))).days
    except ValueError:
        return None


def stale_hint() -> str:
    """Câu nhắc khi yt-dlp đang dùng đã cũ (rỗng nếu còn mới)."""
    ver = loaded_version()
    age = age_days(ver)
    if age is not None and age > STALE_DAYS:
        return f"yt-dlp đang dùng ({ver}) đã {age} ngày chưa cập nhật, có thể là nguyên nhân gây lỗi. Vào Cài đặt > Chung để cập nhật."
    return ""


def latest_version() -> str:
    try:
        r = requests.get(PYPI_URL, timeout=15)
        ver = str(r.json()["info"]["version"])
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(config.redact(f"Không kiểm tra được phiên bản mới nhất ({type(exc).__name__}). Kiểm tra kết nối mạng.")) from None
    if not _key(ver):
        raise RuntimeError("PyPI trả về phiên bản không đọc được.")
    return ver


def _load() -> dict:
    try:
        d = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (ValueError, OSError):
        return {}


def _save(**changes) -> dict:
    state = _load()
    state.update(changes)
    try:
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    return state


def status() -> dict:
    st = _load()
    return {
        "loaded": loaded_version(),
        "installed": installed_version(),
        "latest": st.get("latest", ""),
        "checked_at": st.get("last_check", ""),
        "pending_restart": pending_restart(),
        "auto": auto_enabled(),
        "service": in_service(),
        "age_days": age_days(loaded_version()),
    }


def _pip(*args: str, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "pip", *args], capture_output=True, text=True, timeout=timeout)


def _installed_in_fresh_process() -> str:
    """Đọc phiên bản yt-dlp bằng một tiến trình Python mới, để chắc bản vừa cài import được."""
    r = subprocess.run(
        [sys.executable, "-c", "import yt_dlp.version as v; print(v.__version__)"],
        capture_output=True, text=True, timeout=60,
    )
    return r.stdout.strip() if r.returncode == 0 else ""


def update(job=None, auto: bool = False) -> str:
    """Cập nhật yt-dlp lên bản mới nhất. Trả về thông điệp kết quả, ném RuntimeError nếu lỗi."""
    def say(msg):
        if job is not None:
            job.log(msg)

    if not _lock.acquire(blocking=False):
        raise RuntimeError("Đang có một lần cập nhật yt-dlp khác chạy.")
    try:
        before = installed_version()
        say(f"Phiên bản đang cài: {before or 'không rõ'}. Hỏi PyPI bản mới nhất...")
        latest = latest_version()
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _save(last_check=now, latest=latest)
        if before and not is_newer(latest, before):
            say(f"Bản mới nhất là {latest}, đang dùng {before}.")
            return f"yt-dlp đã là bản mới nhất ({before})."
        say(f"Cập nhật {before or '?'} → {latest} (pip install)...")
        try:
            r = _pip("install", "--quiet", "--disable-pip-version-check", f"yt-dlp=={latest}")
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(f"Không chạy được pip ({type(exc).__name__}).") from None
        if r.returncode != 0:
            tail = " ".join((r.stderr or r.stdout or "").strip().splitlines()[-3:])
            raise RuntimeError(config.redact(f"pip báo lỗi: {tail}")[:400])
        got = _installed_in_fresh_process()
        if not got or _key(got) != _key(latest):
            say(f"Bản vừa cài không chạy được (đọc ra '{got or 'lỗi'}'). Trả về bản cũ {before}...")
            if before:
                try:
                    _pip("install", "--quiet", "--disable-pip-version-check", f"yt-dlp=={before}")
                except (OSError, subprocess.SubprocessError):
                    pass
            raise RuntimeError(f"Cập nhật lên {latest} không thành công nên giữ bản {before or 'cũ'}.")
        _save(updated_from=before, updated_to=latest, updated_at=now, restart_requested=bool(auto))
        msg = f"Đã cập nhật yt-dlp {before or '?'} → {latest}."
        if pending_restart():
            msg += " Cần khởi động lại app để dùng bản mới."
        say(msg)
        return msg
    finally:
        _lock.release()


def update_job(job) -> str:
    return update(job, auto=False)


def _notify(title: str, body: str, key: str, ttl: float = 24) -> None:
    try:
        from . import notify
        notify.send(title, body, key=key, ttl_hours=ttl)
    except Exception:  # noqa: BLE001
        pass


def restart_now(manager) -> None:
    """Thoát tiến trình để launchd bật lại (chỉ khi chạy dưới service.sh và không có tác vụ nào đang chạy)."""
    from . import commenter
    if not in_service():
        raise RuntimeError("App không chạy bằng service.sh nên không tự khởi động lại được. Bấm Ctrl+C rồi chạy lại ./run.sh.")
    if not commenter._lock.acquire(timeout=20):   # đang gửi comment dở thì đợi, tránh comment trùng khi chạy lại
        raise RuntimeError("Đang gửi comment, thử lại sau ít phút.")
    with manager._lock:
        if any(j.status == "running" and j.kind != "comment-worker" for j in manager._jobs.values()):
            commenter._lock.release()
            raise RuntimeError("Đang có tác vụ chạy, đợi xong rồi khởi động lại.")
        os._exit(0)   # giữ khóa đến lúc thoát nên không tác vụ mới nào kịp bắt đầu


def tick(manager, job) -> None:
    """Gọi mỗi phút từ tiến trình nền: tự kiểm tra, cập nhật và (khi chạy nền) khởi động lại."""
    if not auto_enabled() or time.time() - _t0 < STARTUP_GRACE:
        return
    st = _load()
    # 1) Đã cập nhật tự động nhưng chưa dùng bản mới: khởi động lại một lần cho mỗi bản
    if pending_restart():
        target = installed_version()
        if in_service() and st.get("restart_requested") and st.get("restart_for") != target and not manager.busy():
            _save(restart_for=target)
            job.log(f"Khởi động lại app để dùng yt-dlp {target}...")
            try:
                restart_now(manager)
            except RuntimeError as exc:
                job.log(f"Chưa khởi động lại được: {exc}")
                _save(restart_for="")
        elif st.get("restart_for") == target and not st.get("restart_warned") == target:
            _save(restart_warned=target)
            job.log(f"Đã khởi động lại nhưng vẫn chưa dùng yt-dlp {target}. Kiểm tra môi trường ảo của app.")
            _notify("yt-dlp chưa áp dụng được", f"Đã cập nhật lên {target} nhưng app vẫn chạy bản {loaded_version()}.", key="ytdlp-apply", ttl=24)
        return
    # 2) Đến hạn kiểm tra (mỗi 24 giờ) và không có tải video đang chạy
    try:
        last = datetime.fromisoformat(st.get("next_check", ""))
    except ValueError:
        last = None
    now = datetime.now(timezone.utc)
    if last is not None and now < last:
        return
    if manager.busy():
        return
    try:
        msg = update(job, auto=True)
        _save(next_check=(now + CHECK_EVERY).isoformat(timespec="seconds"))
        if "Đã cập nhật" in msg:
            _notify("Đã cập nhật yt-dlp", msg + (" App sẽ tự khởi động lại khi rảnh." if in_service() else " Hãy khởi động lại app."), key=f"ytdlp-up:{installed_version()}", ttl=72)
    except RuntimeError as exc:
        _save(next_check=(now + RETRY_AFTER_FAIL).isoformat(timespec="seconds"))
        job.log(f"Tự cập nhật yt-dlp lỗi: {exc}")
        _notify("Không cập nhật được yt-dlp", str(exc)[:300], key="ytdlp-fail", ttl=24)
