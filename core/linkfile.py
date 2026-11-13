"""File .txt chứa link tải: chọn file bằng hộp thoại của macOS (để server biết đường dẫn thật),
xoá dần link đã xong khỏi file, và gom danh sách link lỗi để báo lại.

Link "đã xong" = đã tải, đã có từ trước, hoặc đã kiểm tra là bài không có video/ảnh nào để tải.
Link lỗi, link bỏ qua vì không đúng loại đã chọn, và link chưa mở tới (dừng giữa chừng) đều giữ nguyên trong file.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import threading
from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024
URL_RE = re.compile(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+", re.I)   # giống downloader.URL_RE

_picked: set[str] = set()   # chỉ ghi vào file .txt mà chính người dùng đã chọn qua hộp thoại (không nhận đường dẫn tuỳ ý từ request)
_lock = threading.Lock()


class PickError(Exception):
    """Lỗi hiện cho người dùng."""


def line_urls(line: str) -> list[str]:
    return [u.rstrip(".,;:!?)]}>") for u in URL_RE.findall(line)]


def check(path: str | Path) -> Path:
    p = Path(path).expanduser()
    if p.suffix.lower() != ".txt":
        raise PickError("Chỉ nhận file .txt.")
    if not p.is_file():
        raise PickError("Không thấy file này.")
    if p.stat().st_size > MAX_BYTES:
        raise PickError("File quá lớn (tối đa 2 MB). Chỉ cần file .txt chứa link.")
    return p.resolve()


def pick() -> Path | None:
    """Mở hộp thoại chọn file của macOS. Trả về None nếu người dùng bấm Huỷ."""
    script = ['activate',   # đưa hộp thoại lên trên cửa sổ trình duyệt
              'POSIX path of (choose file with prompt "Chọn file .txt chứa link" of type {"txt", "public.plain-text"})']
    try:
        r = subprocess.run(["osascript", "-e", script[0], "-e", script[1]], capture_output=True, text=True, timeout=600)
    except FileNotFoundError as exc:
        raise PickError("Máy này không có osascript (chỉ chạy trên macOS).") from exc
    except subprocess.TimeoutExpired as exc:
        raise PickError("Hết giờ chờ chọn file.") from exc
    if r.returncode != 0:
        if "-128" in r.stderr:   # người dùng bấm Huỷ
            return None
        raise PickError("Không mở được hộp thoại chọn file: " + (r.stderr.strip()[:200] or f"mã {r.returncode}"))
    p = check(r.stdout.strip())
    with _lock:
        _picked.add(str(p))
    return p


def is_picked(path: str) -> bool:
    try:
        p = str(Path(path).expanduser().resolve())
    except (OSError, RuntimeError):
        return False
    with _lock:
        return p in _picked


def read_text(p: Path) -> str:
    """Đọc nguyên văn (giữ CRLF, BOM, byte lạ) để ghi lại không làm đổi phần không bị xoá."""
    with open(p, encoding="utf-8", errors="surrogateescape", newline="") as f:
        return f.read()


class LinkBook:
    """Ghi nhận kết quả từng link trong một lần tải."""

    def __init__(self, txt_paths=()):
        self.paths = list(dict.fromkeys(Path(p) for p in (txt_paths or []) if p))
        self.done: set[str] = set()
        self.errors: dict[str, str] = {}   # link -> lý do (giữ thứ tự)
        self.removed = 0
        self.write_errors: dict[Path, str] = {}

    def mark_done(self, link: str | None) -> None:
        if not link or link in self.done:
            return
        self.done.add(link)
        self.errors.pop(link, None)
        self._rewrite()

    def mark_error(self, link: str | None, reason: str) -> None:
        if link and link not in self.done:
            self.errors[link] = " ".join(str(reason).split())[:300]

    def _rewrite(self) -> None:
        for p in self.paths:
            if p not in self.write_errors:
                self._rewrite_one(p)

    def _rewrite_one(self, path: Path) -> None:
        """Bỏ khỏi file mọi dòng mà tất cả link trong dòng đều đã xong. Dòng không có link giữ nguyên."""
        try:
            with _lock:
                text = read_text(path)
                keep, dropped = [], 0
                for line in text.splitlines(keepends=True):
                    urls = line_urls(line)
                    if urls and all(u in self.done for u in urls):
                        dropped += 1
                    else:
                        keep.append(line)
                if not dropped:
                    return
                fd, tmp = tempfile.mkstemp(prefix=".links-", suffix=".tmp", dir=str(path.parent))
                try:
                    with os.fdopen(fd, "w", encoding="utf-8", errors="surrogateescape", newline="") as f:
                        f.write("".join(keep))
                    os.chmod(tmp, path.stat().st_mode & 0o777)
                    os.replace(tmp, path)
                except BaseException:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
                    raise
                self.removed += dropped
        except OSError as exc:
            self.write_errors[path] = f"Không sửa được file {path.name}: {exc}"

    def report(self, job) -> None:
        for msg in self.write_errors.values():
            job.log(msg)
        if self.removed:
            job.log(f"Đã xoá {self.removed} dòng link đã xong khỏi file " + ", ".join(p.name for p in self.paths) + ".")
        if self.errors:
            job.log(f"Có {len(self.errors)} link lỗi, cần tự mở kiểm tra (vẫn giữ trong file):")
            for link, why in self.errors.items():
                job.log(f"  • {link}  ({why})")
        job.data["link_errors"] = [{"url": u, "reason": r} for u, r in self.errors.items()]
        job.data["links_removed"] = self.removed
