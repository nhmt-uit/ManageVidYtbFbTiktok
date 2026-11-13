"""Cổng kiểm soát mọi lệnh gọi Facebook Graph API (hẹn giờ, huỷ, đổi giờ, kiểm tra trạng thái, comment, token).

Vì sao cần: Facebook giới hạn số lượt gọi theo giờ cho CẢ APP (khoảng 200 x số người dùng của app mỗi giờ, cửa sổ trượt;
app chỉ có một người dùng thì khoảng 200 lượt/giờ) và theo Page (4800 x số người tương tác mỗi 24 giờ). Khi chạm giới hạn,
Facebook trả lỗi code 4 / 17 / 613 và tài liệu dặn: DỪNG gọi, vì cứ gọi tiếp chỉ kéo dài thời gian bị chặn.

Mọi lệnh gọi Graph API của app đều đi qua `request()`; cổng này:
  1. Đếm số lượt gọi trong 60 phút qua (lưu ra file nên khởi động lại app không mất) và tự dừng khi hết ngân sách
     FB_CALLS_PER_HOUR (mặc định 150, chừa khoảng 25% so với mức 200 của Facebook).
  2. Chia ngân sách: việc chạy nền (kiểm tra trạng thái định kỳ, comment) chỉ được dùng một phần để luôn chừa chỗ cho
     thao tác của bạn (hẹn giờ, huỷ, kiểm tra tay).
  3. Giãn nhịp giữa các lượt gọi, chậm hơn nữa khi mức dùng đã cao.
  4. Đọc header Facebook trả về (X-App-Usage, X-Business-Use-Case-Usage, X-Page-Usage): mức dùng thật từ 85% trở lên
     thì tự dừng trước khi bị chặn; header báo "estimated_time_to_regain_access" thì dừng đúng thời gian đó.
  5. Facebook báo giới hạn lượt gọi (code 4, 17, 613) thì dừng MỌI thao tác gọi Facebook một thời gian (mặc định 60 phút).
Mã báo giới hạn lượt gọi: 4, 17, 613 (cả app), 80000-80014 (theo Page / sản phẩm) và HTTP 429.
Giới hạn riêng của từng Page vì đăng dày (code 32, 368 hoặc thông báo spam) vẫn do pages.mark_blocked xử lý như trước.
Phanh mềm (mức dùng >= 85%) chỉ chặn việc mới; thao tác đã bắt đầu (tải lên, hoàn tất một lần hẹn giờ) vẫn được làm nốt để không bỏ dở.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import requests

from . import config, ratelimit

WINDOW = 3600                 # giây: cửa sổ trượt tính lượt gọi
SHARE_POLL = 0.25             # kiểm tra trạng thái nền chỉ được dùng tối đa ngần này ngân sách
SHARE_BG = 0.60               # nền (kiểm tra + comment) tối đa ngần này, phần còn lại dành cho thao tác của người dùng
WARN_PCT = 70                 # từ mức này trở lên: giãn nhịp chậm hơn, báo vàng
BRAKE_PCT = 85                # Facebook báo đã dùng từ mức này: tự dừng trước khi bị chặn
BRAKE_MINUTES = 10            # dừng bao lâu khi chạm BRAKE_PCT (sau đó thử lại một lượt để đọc lại mức dùng)
TRIP_MINUTES = 60             # dừng bao lâu khi Facebook đã báo giới hạn lượt gọi mà không nói thời gian
MAX_SLEEP = 30                # giây: giãn nhịp lâu hơn mức này thì báo dừng thay vì ngủ
COSTS = {"schedule": 3, "cancel": 1, "retime": 1, "check": 1, "comment": 2}   # lượt gọi ước tính cho một video

CLASSES = ("user", "comment", "poll")


class RateLimited(Exception):
    """Không gọi Facebook lúc này. local=True: app tự dừng (hết ngân sách), False: Facebook đã báo giới hạn hoặc mức dùng quá cao."""

    def __init__(self, message: str, minutes: float = 1, local: bool = True):
        super().__init__(message)
        self.minutes = max(1, int(math.ceil(minutes)))
        self.local = local

    @property
    def hours(self) -> int:
        return max(1, int(math.ceil(self.minutes / 60)))


def budget() -> int:
    return config.get_int("FB_CALLS_PER_HOUR", 150, 20, 5000)


def _min_interval() -> float:
    try:
        return min(max(float(config.get("FB_MIN_INTERVAL_SECONDS") or 0.6), 0.0), 10.0)
    except (TypeError, ValueError):
        return 0.6


def _state_file() -> Path:
    return Path(os.environ.get("FBGATE_STATE") or (config.ROOT / "fbgate_state.json"))


def _hget(headers, name: str):
    if not headers:
        return None
    try:
        v = headers.get(name)
        if v is None:
            v = headers.get(name.title())
        if v is None:
            for k in headers:
                if str(k).lower() == name:
                    return headers[k]
        return v
    except Exception:  # noqa: BLE001
        return None


def _json_header(value):
    if not value:
        return None
    try:
        d = json.loads(value) if isinstance(value, (str, bytes)) else value
    except ValueError:
        return None
    return d if isinstance(d, (dict, list)) else None


def _pct(d, key) -> float:
    try:
        return float(d.get(key) or 0)
    except (TypeError, ValueError, AttributeError):
        return 0.0


class Gate:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tls = threading.local()
        self._next_at = 0.0
        self._loaded = False
        self._saved_at = 0.0
        self.calls: list[list] = []        # [giờ, lớp]
        self.cooldown_until = 0.0
        self.cooldown_reason = ""
        self.cooldown_kind = ""            # facebook | usage
        self.usage: dict = {}              # app / page: {"call_count","total_cputime","total_time","eta","at"}

    # ---------- trạng thái lưu ra file ----------
    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            d = json.loads(_state_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(d, dict):
            return
        now = time.time()
        try:
            self.calls = [[float(t), c if c in CLASSES else "user"] for t, c in (d.get("calls") or [])
                          if isinstance(t, (int, float)) and now - t < WINDOW]
            self.cooldown_until = float(d.get("cooldown_until") or 0)
            self.cooldown_reason = str(d.get("cooldown_reason") or "")
            self.cooldown_kind = str(d.get("cooldown_kind") or "")
            self.usage = d.get("usage") if isinstance(d.get("usage"), dict) else {}
        except (TypeError, ValueError):
            self.calls, self.cooldown_until, self.cooldown_reason, self.cooldown_kind, self.usage = [], 0.0, "", "", {}   # file hỏng: bắt đầu lại

    def _save(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._saved_at < 2:
            return
        self._saved_at = now
        data = {"calls": self.calls, "cooldown_until": self.cooldown_until, "cooldown_reason": self.cooldown_reason,
                "cooldown_kind": self.cooldown_kind, "usage": self.usage}
        try:
            path = _state_file()
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            pass

    def _purge(self, now: float) -> None:
        self.calls = [c for c in self.calls if now - c[0] < WINDOW]

    def reset(self) -> None:
        """Xóa mọi số đếm và trạng thái dừng (dùng khi kiểm thử)."""
        with self._lock:
            self._loaded = True
            self.calls, self.cooldown_until, self.cooldown_reason, self.cooldown_kind, self.usage = [], 0.0, "", "", {}
            self._next_at = 0.0
            self._save(force=True)

    @contextmanager
    def keep_free(self, n: int):
        """Trong khối này, mọi lượt gọi của luồng hiện tại chừa lại ít nhất `n` lượt trong giờ cho việc khác (thao tác hàng loạt)."""
        prev = getattr(self._tls, "reserve", 0)
        self._tls.reserve = max(prev, int(n))
        try:
            yield
        finally:
            self._tls.reserve = prev

    def mark_background(self, on: bool = True) -> None:
        """Gọi trong luồng chạy nền: mọi lượt đọc trạng thái của luồng này tính vào phần ngân sách của nền."""
        self._tls.bg = on

    # ---------- đo ----------
    def _counts(self) -> dict:
        c = {k: 0 for k in CLASSES}
        for _, cls in self.calls:
            c[cls] = c.get(cls, 0) + 1
        return c

    def _limits(self) -> dict:
        b = budget()
        return {"total": b, "bg": int(b * SHARE_BG), "poll": int(b * SHARE_POLL)}

    def _wait_minutes(self, classes: tuple, limit: int, now: float, need: int = 1) -> float:
        """Bao lâu nữa thì có chỗ cho `need` lượt gọi mới (các lượt cũ nhất hết hạn khỏi cửa sổ 60 phút)."""
        times = sorted(t for t, c in self.calls if c in classes)
        over = len(times) - limit + need       # cần bớt ngần này lượt cũ thì đủ chỗ
        if over <= 0:
            return 1
        if over > len(times):
            return WINDOW / 60
        return max(1.0, (times[over - 1] + WINDOW - now) / 60)

    def paused(self) -> int:
        """Số phút còn phải dừng (0 = không dừng)."""
        with self._lock:
            self._load()
            left = self.cooldown_until - time.time()
            return max(1, int(math.ceil(left / 60))) if left > 0 else 0

    def affordable(self, cls: str = "user", reserve: int = 0) -> int:
        """Còn bao nhiêu lượt gọi dùng được cho lớp này trong giờ này (reserve: chừa lại ngần này lượt cho việc khác)."""
        with self._lock:
            self._load()
            now = time.time()
            self._purge(now)
            if self.cooldown_until > now:
                return 0
            cnt, lim = self._counts(), self._limits()
            room = lim["total"] - reserve - sum(cnt.values())
            if cls == "poll":
                room = min(room, lim["poll"] - cnt["poll"], lim["bg"] - cnt["poll"] - cnt["comment"])
            elif cls == "comment":
                room = min(room, lim["bg"] - cnt["poll"] - cnt["comment"])
            return max(0, room)

    # ---------- trước khi gọi ----------
    def _blocked(self, cls: str, weight: int, reserve: int, now: float):
        """RateLimited nếu lúc này không được gọi `weight` lượt (không ghi nhận gì), ngược lại None. Gọi khi đã giữ khoá."""
        # Phanh mềm (kind="usage", mức dùng ≥85%) chỉ chặn việc MỚI. Bước nối tiếp của thao tác đã bắt đầu (weight=0, ví dụ tải lên và hoàn tất
        # sau khi đã gọi bước bắt đầu) vẫn được đi tiếp, nếu không sẽ bỏ dở: video tải lên mà không hẹn giờ. Chỉ khi Facebook đã báo giới hạn thật mới chặn hết.
        if self.cooldown_until > now and not (weight == 0 and self.cooldown_kind == "usage"):
            m = (self.cooldown_until - now) / 60
            return RateLimited(
                f"Facebook đang giới hạn lượt gọi API ({self.cooldown_reason or 'đã chạm giới hạn'}): app dừng gọi Facebook để không bị chặn lâu hơn. "
                f"Thử lại sau khoảng {math.ceil(m)} phút.", m, local=False)
        if not weight:
            return None
        cnt, lim = self._counts(), self._limits()
        used = sum(cnt.values())
        bg_used = cnt["poll"] + cnt["comment"]
        wait = None
        if used + weight > lim["total"] - reserve:
            wait = self._wait_minutes(CLASSES, lim["total"] - reserve, now, weight)
        elif cls == "poll" and cnt["poll"] + weight > lim["poll"]:
            wait = self._wait_minutes(("poll",), lim["poll"], now, weight)
        elif cls in ("poll", "comment") and bg_used + weight > lim["bg"]:
            wait = self._wait_minutes(("poll", "comment"), lim["bg"], now, weight)
        if wait is None:
            return None
        if cls == "user":
            why = f"App đã dùng {used}/{lim['total']} lượt gọi Facebook trong 60 phút qua" + (
                f" (việc hàng loạt này chừa lại {reserve} lượt cho hẹn giờ, huỷ, comment)" if reserve else "")
        else:
            why = f"Việc chạy nền đã dùng {bg_used}/{lim['bg']} lượt gọi Facebook được phép trong 60 phút qua (chừa chỗ cho thao tác của bạn)"
        return RateLimited(
            f"{why} nên app tự dừng để không chạm giới hạn của Facebook. Thử lại sau khoảng {math.ceil(wait)} phút. "
            "Đổi mức này ở Cài đặt > Chung (Số lượt gọi Facebook tối đa mỗi giờ).", wait, local=True)

    def why_not(self, weight: int = 1, cls: str = "user", reserve: int = 0) -> str:
        """Lý do chưa gọi được `weight` lượt lúc này (chuỗi rỗng nếu gọi được). Không ghi nhận lượt nào."""
        with self._lock:
            self._load()
            now = time.time()
            self._purge(now)
            exc = self._blocked(cls, max(0, int(weight)), max(int(reserve), getattr(self._tls, "reserve", 0)), now)
            return str(exc) if exc else ""

    def acquire(self, cls: str = "user", weight: int = 1, reserve: int = 0) -> None:
        """Xin `weight` lượt gọi (0 = chỉ kiểm tra có đang bị dừng không, dùng cho bước nối tiếp của một thao tác đã trả phí)."""
        if cls == "user" and getattr(self._tls, "bg", False):
            cls = "poll"
        if cls not in CLASSES:
            cls = "user"
        weight = max(0, int(weight))
        reserve = max(int(reserve), getattr(self._tls, "reserve", 0))
        with self._lock:
            self._load()
            now = time.time()
            self._purge(now)
            exc = self._blocked(cls, weight, reserve, now)
            if exc:
                raise exc
            if not weight:
                return
            cnt, lim = self._counts(), self._limits()
            used = sum(cnt.values())
            # giãn nhịp: chậm hơn khi nền chạy hoặc mức dùng đã cao
            interval = _min_interval()
            if interval:
                high = used >= lim["total"] * WARN_PCT / 100 or self._worst() >= WARN_PCT
                interval *= (3 if high else 1) * (3 if cls == "poll" else 1)
            slot = max(now, self._next_at)
            self._next_at = slot + interval * weight
            sleep = slot - now
            if sleep > MAX_SLEEP:
                self._next_at = slot
                raise RateLimited("Đang có quá nhiều thao tác gọi Facebook cùng lúc, thử lại sau ít phút.", 1, local=True)
            for _ in range(weight):
                self.calls.append([slot, cls])
            self._save()
        if sleep > 0:
            time.sleep(sleep)

    def _worst(self) -> float:
        now = time.time()
        w = 0.0
        for v in self.usage.values():
            if isinstance(v, dict) and now - float(v.get("at") or 0) < 1800:
                w = max(w, _pct(v, "call_count"), _pct(v, "total_cputime"), _pct(v, "total_time"))
        return w

    # ---------- sau khi gọi ----------
    def trip(self, minutes: float, reason: str, kind: str = "facebook") -> None:
        with self._lock:
            self._load()
            until = time.time() + minutes * 60
            if until > self.cooldown_until:
                self.cooldown_until, self.cooldown_reason, self.cooldown_kind = until, reason, kind
            self._save(force=True)
            used = len(self.calls)
        if kind == "facebook":
            try:
                from . import notify
                notify.send(
                    "Facebook giới hạn lượt gọi",
                    f"App tạm dừng mọi thao tác gọi Facebook khoảng {math.ceil(minutes)} phút ({reason}). Đã dùng {used} lượt trong giờ qua. Không cần làm gì thêm.",
                    key="fbgate-trip", ttl_hours=2)
            except Exception:  # noqa: BLE001
                pass

    def clear_cooldown(self) -> None:
        with self._lock:
            self._load()
            self.cooldown_until, self.cooldown_reason, self.cooldown_kind = 0.0, "", ""
            self._save(force=True)

    def observe(self, resp) -> None:
        """Đọc header mức dùng và mã lỗi giới hạn từ phản hồi của Facebook."""
        headers = getattr(resp, "headers", None)
        now = time.time()
        eta = 0.0
        seen = {}
        app = _json_header(_hget(headers, "x-app-usage"))
        if isinstance(app, dict):
            seen["app"] = {"call_count": _pct(app, "call_count"), "total_cputime": _pct(app, "total_cputime"), "total_time": _pct(app, "total_time")}
        buc = _json_header(_hget(headers, "x-business-use-case-usage"))
        if isinstance(buc, dict):
            best = {"call_count": 0.0, "total_cputime": 0.0, "total_time": 0.0}
            for items in buc.values():
                for it in items if isinstance(items, list) else []:
                    if not isinstance(it, dict):
                        continue
                    for k in best:
                        best[k] = max(best[k], _pct(it, k))
                    eta = max(eta, _pct(it, "estimated_time_to_regain_access"))
            seen["page"] = best
        pg = _json_header(_hget(headers, "x-page-usage"))
        if isinstance(pg, dict):
            seen["page"] = {k: max(_pct(pg, k), seen.get("page", {}).get(k, 0.0)) for k in ("call_count", "total_cputime", "total_time")}
        trip_min, reason = 0.0, ""
        status = getattr(resp, "status_code", 200)
        if isinstance(status, int) and status >= 400:
            try:
                err = (resp.json() or {}).get("error", {})
            except Exception:  # noqa: BLE001
                err = {}
            code = err.get("code") if isinstance(err, dict) else None
            try:
                code = int(code)
            except (TypeError, ValueError):
                code = None
            if code in ratelimit.CALL_LIMIT_CODES:   # 4, 17, 613: cả app; 80000-80014: theo Page / sản phẩm
                trip_min = max(eta, TRIP_MINUTES)
                reason = f"Facebook báo code {code}"
            elif status == 429:   # HTTP 429 Too Many Requests, dù thân phản hồi không có mã lỗi
                trip_min = max(eta, TRIP_MINUTES)
                reason = "Facebook báo HTTP 429"
        with self._lock:
            self._load()
            for k, v in seen.items():
                v["eta"] = eta
                v["at"] = now
                self.usage[k] = v
            self._save()
        if trip_min:
            self.trip(trip_min, reason)
        elif eta > 0:
            self.trip(eta, f"Facebook báo còn khoảng {math.ceil(eta)} phút mới gọi lại được")
        else:
            worst = max([max(_pct(v, "call_count"), _pct(v, "total_cputime"), _pct(v, "total_time")) for v in seen.values()] or [0.0])
            if worst >= BRAKE_PCT:
                self.trip(BRAKE_MINUTES, f"Facebook báo app đã dùng {worst:.0f}% hạn mức", kind="usage")

    # ---------- cho giao diện ----------
    def status(self) -> dict:
        with self._lock:
            self._load()
            now = time.time()
            self._purge(now)
            cnt, lim = self._counts(), self._limits()
            used = sum(cnt.values())
            paused = self.paused()
            worst = self._worst()
            level = "bad" if paused or used >= lim["total"] else ("warn" if used >= lim["total"] * WARN_PCT / 100 or worst >= WARN_PCT else "ok")
            oldest = min((t for t, _ in self.calls), default=None)
            return {
                "budget": lim["total"], "used": used, "remaining": max(0, lim["total"] - used),
                "user_used": cnt["user"], "comment_used": cnt["comment"], "poll_used": cnt["poll"],
                "bg_limit": lim["bg"], "poll_limit": lim["poll"],
                "paused_minutes": paused, "paused_reason": self.cooldown_reason if paused else "",
                "paused_kind": self.cooldown_kind if paused else "",
                "usage": {k: {kk: vv for kk, vv in v.items() if kk != "at"} for k, v in self.usage.items()
                          if isinstance(v, dict) and now - float(v.get("at") or 0) < 1800},
                "level": level,
                "oldest_minutes": int((now - oldest) / 60) if oldest else 0,
                "next_free_minutes": max(1, int(math.ceil((oldest + WINDOW - now) / 60))) if oldest else 0,
                "costs": COSTS,
            }


gate = Gate()


def request(method: str, url: str, *, cls: str = "user", weight: int = 1, reserve: int = 0, **kwargs):
    """Gọi Facebook qua cổng kiểm soát. Ném RateLimited (chưa gọi gì) nếu đang bị giới hạn hoặc hết ngân sách.

    weight: số lượt gọi tính cho lệnh này (hẹn giờ một Reel = 3: bắt đầu, tải lên, hoàn tất; hai bước sau gọi với weight=0).
    reserve: chừa lại ngần này lượt trong giờ cho việc khác (dùng cho thao tác hàng loạt).
    """
    gate.acquire(cls, weight, reserve)
    resp = getattr(requests, method)(url, **kwargs)   # tra cứu lúc gọi để kiểm thử thay thế được requests.get/post/delete
    gate.observe(resp)
    return resp


keep_free = gate.keep_free
mark_background = gate.mark_background


def why_not(weight: int = 1, cls: str = "user", reserve: int = 0) -> str:
    return gate.why_not(weight, cls, reserve)


def paused() -> int:
    return gate.paused()


def affordable(cls: str = "user", reserve: int = 0) -> int:
    return gate.affordable(cls, reserve)
