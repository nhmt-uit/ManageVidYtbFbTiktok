"""Chạy tác vụ nền (tải, hẹn giờ) và giữ nhật ký để giao diện theo dõi.

Nhật ký có thể lưu ra file (logs/jobs/*.jsonl, mỗi tác vụ một file) để xem lại sau khi app khởi động lại.
Chỉ bật khi app chạy thật (manager.enable_persistence trong app.py), nên các bài test không ghi file.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from . import config

LOG_LINES_MAX = 3000        # số dòng nhật ký giữ trong bộ nhớ cho mỗi tác vụ (dòng cũ hơn bị bỏ)
FILE_LINES_MAX = 6000       # số dòng tối đa ghi ra file cho mỗi tác vụ
KEEP_JOBS_MEMORY = 200      # số tác vụ đã xong giữ trong bộ nhớ
KEEP_FILES = 150            # số file nhật ký giữ lại trên đĩa
KEEP_DAYS = 30              # file nhật ký cũ hơn số ngày này bị xóa
WORKER_KINDS = ("comment-worker",)   # tiến trình nền chạy mãi, không phải tác vụ có điểm kết thúc


class JobStore:
    """Ghi và nạp nhật ký tác vụ. Mọi lỗi đĩa chỉ bị bỏ qua, không làm hỏng tác vụ."""

    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self._lock = threading.Lock()

    def _path(self, job: "Job") -> Path:
        return self.dir / f"{job.created:%Y%m%d-%H%M%S}_{job.id}.jsonl"

    def _write(self, job: "Job", event: dict) -> None:
        line = json.dumps(event, ensure_ascii=False) + "\n"
        try:
            with self._lock:
                self.dir.mkdir(parents=True, exist_ok=True)
                path = self._path(job)
                new = not path.exists()
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line)
                if new:
                    os.chmod(path, 0o600)
        except OSError:
            pass

    def start(self, job: "Job") -> None:
        self._write(job, {"t": "start", "id": job.id, "kind": job.kind, "title": job.title,
                          "page_id": job.page_id, "created": job.created.isoformat()})

    def log(self, job: "Job", line: str) -> None:
        if job.file_lines < FILE_LINES_MAX:
            job.file_lines += 1
            self._write(job, {"t": "log", "m": line})
        elif job.file_lines == FILE_LINES_MAX:
            job.file_lines += 1
            self._write(job, {"t": "log", "m": "... (nhật ký quá dài, các dòng sau không được lưu ra file)"})

    def finish(self, job: "Job") -> None:
        self._write(job, {"t": "end", "status": job.status, "result": job.result,
                          "done": job.done, "total": job.total})

    def load(self) -> list["Job"]:
        """Đọc lại các tác vụ đã lưu (mới nhất trước). Tác vụ không có dòng kết thúc là bị gián đoạn khi app tắt."""
        jobs: list[Job] = []
        try:
            files = sorted(self.dir.glob("*.jsonl"), reverse=True)[:KEEP_FILES]
        except OSError:
            return jobs
        for path in files:
            job = self._read(path)
            if job is not None:
                jobs.append(job)
        return jobs

    def _read(self, path: Path) -> "Job | None":
        job = None
        ended = False
        try:
            with open(path, encoding="utf-8") as f:
                for raw in f:
                    try:
                        ev = json.loads(raw)
                    except ValueError:
                        continue
                    if not isinstance(ev, dict):
                        continue
                    kind = ev.get("t")
                    if kind == "start" and job is None:
                        job = Job(str(ev.get("kind") or ""), str(ev.get("title") or ""), str(ev.get("page_id") or ""))
                        job.id = str(ev.get("id") or job.id)
                        try:
                            job.created = datetime.fromisoformat(str(ev.get("created")))
                        except ValueError:
                            pass
                        job.status = "done"
                    elif job is None:
                        continue
                    elif kind == "log":
                        job.logs.append(str(ev.get("m", "")))
                    elif kind == "end":
                        ended = True
                        job.status = ev.get("status") if ev.get("status") in ("done", "error", "cancelled") else "done"
                        job.result = str(ev.get("result") or "")
                        job.done, job.total = int(ev.get("done") or 0), int(ev.get("total") or 0)
        except (OSError, ValueError):
            return None
        if job is None:
            return None
        if len(job.logs) > LOG_LINES_MAX:
            job.base = len(job.logs) - LOG_LINES_MAX
            job.logs = job.logs[-LOG_LINES_MAX:]
        job.file_lines = FILE_LINES_MAX + 1   # tác vụ đã nạp lại không ghi thêm
        if not ended:
            if job.kind in WORKER_KINDS:
                job.status, job.result = "cancelled", "App đã tắt."
            else:
                job.status, job.result = "error", "Bị gián đoạn vì app đã tắt hoặc khởi động lại khi tác vụ đang chạy."
        return job

    def prune(self) -> None:
        """Xóa file nhật ký cũ hơn KEEP_DAYS ngày hoặc vượt quá KEEP_FILES file."""
        try:
            files = sorted(self.dir.glob("*.jsonl"), reverse=True)
        except OSError:
            return
        cutoff = datetime.now() - timedelta(days=KEEP_DAYS)
        for i, path in enumerate(files):
            try:
                old = datetime.fromtimestamp(path.stat().st_mtime) < cutoff
                if i >= KEEP_FILES or old:
                    path.unlink()
            except OSError:
                pass


class Job:
    def __init__(self, kind: str, title: str, page_id: str = ""):
        self.id = uuid.uuid4().hex[:8]
        self.page_id = page_id
        self.kind = kind
        self.title = title
        self.status = "running"  # running | done | error | cancelled
        self.logs: list[str] = []
        self.base = 0            # số dòng đã bỏ khỏi đầu `logs` (để chỉ số `since` của giao diện vẫn đúng)
        self.done = 0
        self.total = 0
        self.result = ""
        self.data: dict = {}     # kết quả có cấu trúc cho giao diện (ví dụ danh sách video bị từ chối), chỉ giữ trong bộ nhớ
        self.created = datetime.now()
        self.cancel_event = threading.Event()
        self.store: JobStore | None = None
        self.file_lines = 0
        self._lock = threading.Lock()

    def log(self, msg: str) -> None:
        line = config.redact(f"{datetime.now():%H:%M:%S}  {msg}")
        with self._lock:
            self.logs.append(line)
            if len(self.logs) > LOG_LINES_MAX:
                drop = len(self.logs) - LOG_LINES_MAX
                del self.logs[:drop]
                self.base += drop
        if self.store is not None:
            self.store.log(self, line)

    def set_progress(self, done: int, total: int) -> None:
        self.done, self.total = done, total

    def finish(self, status: str, result: str) -> None:
        self.result = result
        self.status = status
        if self.store is not None:
            self.store.finish(self)

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def snapshot(self, since: int = 0) -> dict:
        with self._lock:
            lines = self.logs[max(0, since - self.base):]
            nxt = self.base + len(self.logs)
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "page_id": self.page_id,
            "status": self.status,
            "created": self.created.strftime("%Y-%m-%d %H:%M:%S"),
            "progress": {"done": self.done, "total": self.total},
            "result": self.result,
            "data": self.data,
            "logs": lines,
            "next": nxt,
        }


class JobManager:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self.store: JobStore | None = None

    def enable_persistence(self, directory: Path) -> None:
        """Bật lưu nhật ký ra file và nạp lại các tác vụ đã lưu từ lần chạy trước."""
        store = JobStore(directory)
        store.prune()
        loaded = store.load()
        with self._lock:
            self.store = store
            for job in loaded:
                self._jobs.setdefault(job.id, job)

    def _register(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.id] = job
            finished = sorted((j for j in self._jobs.values() if j.status != "running"), key=lambda j: j.created)
            for old in finished[: max(0, len(finished) - KEEP_JOBS_MEMORY)]:
                self._jobs.pop(old.id, None)
        if self.store is not None:
            job.store = self.store
            self.store.start(job)

    def start(self, kind: str, title: str, fn, *args, page_id: str = "") -> Job:
        job = Job(kind, title, page_id)
        self._register(job)

        def runner():
            try:
                result = fn(job, *args) or ""
                job.finish("cancelled" if job.cancelled else "done", result)
            except Exception as exc:  # noqa: BLE001
                job.log(f"LỖI: {config.redact(exc)}")
                job.finish("error", config.redact(exc))

        threading.Thread(target=runner, daemon=True).start()
        return job

    def create(self, kind: str, title: str) -> Job:
        """Tạo job không gắn luồng chạy riêng (cho tiến trình nền tự quản lý)."""
        job = Job(kind, title)
        self._register(job)
        return job

    def get(self, job_id: str):
        return self._jobs.get(job_id)

    def list(self) -> list[dict]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created, reverse=True)
        return [
            {
                "id": j.id,
                "kind": j.kind,
                "title": j.title,
                "page_id": j.page_id,
                "status": j.status,
                "created": j.created.strftime("%Y-%m-%d %H:%M:%S"),
                "progress": {"done": j.done, "total": j.total},
            }
            for j in jobs
        ]

    def has_running(self, kind: str, page_id: str | None = None) -> bool:
        with self._lock:
            return any(
                j.kind == kind and j.status == "running" and (page_id is None or j.page_id == page_id)
                for j in self._jobs.values()
            )

    def busy(self) -> bool:
        """Có tác vụ nào đang chạy không (không tính tiến trình nền chạy mãi như tự động comment)."""
        with self._lock:
            return any(j.status == "running" and j.kind not in WORKER_KINDS for j in self._jobs.values())


manager = JobManager()
