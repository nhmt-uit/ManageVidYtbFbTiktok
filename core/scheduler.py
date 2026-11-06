"""Hẹn giờ đăng Reels lên Facebook Page qua Graph API."""
from __future__ import annotations

import json
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from . import commenter, config, fbgate, library, pages, planner, ratelimit, reelcheck
from .videofile import video_file


class FacebookError(RuntimeError):
    """Lỗi do Facebook trả về, giữ lại mã lỗi để nhận biết giới hạn tần suất."""

    def __init__(self, step: str, message, code=None, subcode=None):
        self.step, self.message, self.code, self.subcode = step, str(message), code, subcode
        extra = f" (code {code}" + (f", subcode {subcode}" if subcode else "") + ")" if code else ""
        super().__init__(f"{step}: {self.message}{extra}")


def _check(resp: requests.Response, step: str) -> dict:
    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError(f"{step}: phản hồi không phải JSON ({resp.status_code}): {resp.text[:300]}")
    if resp.status_code >= 400 or "error" in data:
        err = data.get("error", data)
        if isinstance(err, dict):
            raise FacebookError(step, err.get("message", err), err.get("code"), err.get("error_subcode"))
        raise FacebookError(step, err)
    return data


def schedule_reel(page_id: str, token: str, video: Path, caption: str, when_ts: int) -> str:
    endpoint = f"{config.graph_url()}/{page_id}/video_reels"

    # Cổng giới hạn: tính trước 3 lượt gọi (bắt đầu, tải lên, hoàn tất) ngay ở bước đầu. Hai bước sau chỉ kiểm tra có đang bị dừng không,
    # để không bỏ dở giữa chừng (tải lên rồi mà không hoàn tất được thì video tải lên bị bỏ phí).
    # 1) khởi tạo phiên upload
    r = fbgate.request("post", endpoint, weight=fbgate.COSTS["schedule"], data={"upload_phase": "start", "access_token": token}, timeout=60)
    start = _check(r, "start")
    video_id, upload_url = start["video_id"], start["upload_url"]

    # 2) upload file
    size = video.stat().st_size
    with open(video, "rb") as f:
        r = fbgate.request(
            "post",
            upload_url,
            weight=0,
            headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)},
            data=f,
            timeout=600,
        )
    up = _check(r, "upload")
    if not up.get("success", True):
        raise RuntimeError(f"upload: {up}")

    # 3) hoàn tất và hẹn giờ
    r = fbgate.request(
        "post",
        endpoint,
        weight=0,
        data={
            "upload_phase": "finish",
            "video_id": video_id,
            "video_state": "SCHEDULED",
            "scheduled_publish_time": str(when_ts),
            "description": caption,
            "access_token": token,
        },
        timeout=120,
    )
    _check(r, "finish")
    return video_id


def recent_created(page_id: str, hours: float = 24) -> list[datetime]:
    """Các lần hẹn giờ (gọi API đăng Reel) của Page trong `hours` giờ qua. Bản ghi cũ chưa có created_at thì lấy giờ sửa file."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    out = []
    for folder in commenter.find_scheduled():
        sched = commenter.read_sched(folder)
        pg = pages.resolve(sched)
        if not pg or pg["id"] != page_id:
            continue
        when = commenter._parse(sched.get("created_at"))
        if when is None:
            # Bản ghi từ trước khi có created_at: lấy giờ sửa file một lần rồi lưu lại, để các lần cập nhật trạng thái
            # về sau không làm video cũ bị tính như mới hẹn
            with commenter._lock:
                sched = commenter.read_sched(folder)
                when = commenter._parse(sched.get("created_at"))
                if when is None and sched:
                    try:
                        when = datetime.fromtimestamp((folder / "scheduled.json").stat().st_mtime, timezone.utc)
                        sched["created_at"] = when.isoformat()
                        commenter.write_sched(folder, sched)
                    except OSError:
                        continue
            if when is None:
                continue
        if when >= cutoff:
            out.append(when.astimezone(timezone.utc))
    # Bài đã huỷ hoặc gỡ lịch vẫn là một lần gọi API đăng Reel: vẫn tính vào giới hạn 24 giờ
    root = config.output_dir()
    if root.exists():
        for p in list(root.glob("*/scheduled.old.json")) + list(root.glob("*/*/scheduled.old.json")):
            sched = commenter.read_sched_file(p)
            pg = pages.resolve(sched)
            when = commenter._parse(sched.get("created_at"))
            if pg and pg["id"] == page_id and when is not None and when >= cutoff:
                out.append(when.astimezone(timezone.utc))
    return sorted(out)


def _pause(job, seconds: float) -> None:
    """Nghỉ giữa hai video (có thể dừng giữa chừng)."""
    for _ in range(int(seconds)):
        if job.cancelled:
            return
        time.sleep(1)


def run(job, page_id: str, rels: list[str], start: str, interval_hours: float, tz_name: str, dry_run: bool,
        mode: str = "interval", order: str = "oldest", partial: bool = False) -> str:
    page = pages.get(page_id)
    if page is None:
        raise RuntimeError("Không tìm thấy Fanpage này. Vào mục Kết nối Fanpage để thêm.")
    token = page.get("token", "")
    if not dry_run and not token:
        raise RuntimeError("Fanpage này chưa có Page token. Vào mục Kết nối Fanpage, lấy lại danh sách từ Facebook.")

    tz = ZoneInfo(tz_name)
    blocked = pages.blocked_until(page)
    if blocked and not dry_run:
        raise RuntimeError(
            f"Facebook đang giới hạn tần suất đăng của Page này, dự kiến đến {blocked.astimezone(tz):%H:%M %d/%m} ({tz_name}). "
            "Đợi hết thời gian này rồi hẹn tiếp để tránh bị chặn lâu hơn. Nếu bạn chắc chắn đã hết bị chặn, bấm \"Bỏ cảnh báo\" ở tab Cài đặt Page."
        )
    first = datetime.strptime(start, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
    if mode != "auto" and first < datetime.now(tz) + timedelta(minutes=15):
        raise RuntimeError("Giờ bắt đầu phải cách hiện tại ít nhất khoảng 15 phút.")

    # Chống trùng: một video YouTube (theo ID) chỉ được hẹn một lần, kể cả khi nó nằm ở nhiều thư mục
    # (chỉ tính trong các thư mục của chính Page này: mỗi Page có kho video riêng)
    idx = library.id_index()
    taken = {
        vid for vid, dirs in idx.items()
        if any((x / "scheduled.json").exists() and library.owner_of(x.parent) == page_id for x in dirs)
    }
    folders = []
    seen = set()
    invalid = 0
    check_on = reelcheck.enabled() and reelcheck.available()
    if reelcheck.enabled() and not reelcheck.available():
        job.log("Lưu ý: chưa cài ffprobe (đi kèm ffmpeg) nên bỏ qua bước kiểm tra video đạt yêu cầu Reels.")
    for rel in rels:
        if rel in seen:
            continue
        seen.add(rel)
        d = library.resolve(rel)
        if library.owner_of(d.parent) != page_id:
            job.log(f"Bỏ qua (thư mục này không thuộc Page đang chọn): {d.name}")
            continue
        if (d / "scheduled.json").exists():
            job.log(f"Bỏ qua (đã hẹn giờ): {d.name}")
            continue
        vid = library.yt_id(d)
        if vid and vid in taken:
            job.log(f"Bỏ qua (video này đã được hẹn ở thư mục khác hoặc bị chọn trùng): {d.name}")
            continue
        if check_on:   # video không đạt yêu cầu Reels thì bỏ qua, không tốn lượt hạn mức 24 giờ
            try:
                res = reelcheck.ensure(d)
            except RuntimeError as exc:
                res = None
                check_on = False
                job.log(f"Lưu ý: bỏ qua bước kiểm tra Reels ({exc})")
            if res and res["errors"]:
                invalid += 1
                job.log(f"Bỏ qua (không đạt yêu cầu Reels): {d.name}: {' '.join(res['errors'])}")
                continue
            if res and res["warnings"]:
                job.log(f"Lưu ý: {d.name}: {' '.join(res['warnings'])}")
        if vid:
            taken.add(vid)
        folders.append(d)

    # Thứ tự đăng: cũ trước (mặc định), mới trước, ngẫu nhiên, hoặc đúng thứ tự bạn đã tích chọn
    if order == "newest":
        folders.sort(key=lambda d: d.name, reverse=True)
    elif order == "random":
        random.shuffle(folders)
    elif order == "selected":
        pass
    else:
        folders.sort(key=lambda d: d.name)

    # Giới hạn số video hẹn giờ mỗi 24 giờ cho một Page (Facebook tính khoảng 30 bài đăng qua API mỗi 24 giờ)
    skipped_left = 0
    eff = pages.effective(page)
    cap = eff["publish_limit_24h"]
    if cap and folders:
        recent = recent_created(page_id)
        remaining = cap - len(recent)
        if remaining <= 0:
            free_at = (recent[0] + timedelta(hours=24)).astimezone(tz)
            raise RuntimeError(
                f"Page này đã hẹn {len(recent)} video trong 24 giờ qua, đạt giới hạn {cap} video/24 giờ. "
                f"Vượt mức này Facebook dễ chặn tạm thời. Có thể hẹn tiếp từ khoảng {free_at:%H:%M %d/%m} ({tz_name}). "
                "Đổi giới hạn ở Cài đặt Page nếu bạn muốn."
            )
        if len(folders) > remaining:
            job.log(
                f"Giới hạn {cap} video/24 giờ cho mỗi Page (đã hẹn {len(recent)} trong 24 giờ qua): "
                f"lần này chỉ xếp {remaining}/{len(folders)} video, phần còn lại để lần sau."
            )
            skipped_left = len(folders) - remaining
            folders = folders[:remaining]
    # Giới hạn lượt gọi Facebook mỗi giờ của cả app (xem fbgate): mỗi video hẹn giờ tốn vài lượt gọi, chỉ xếp số video còn đủ lượt
    if folders and not dry_run:
        wait_min = fbgate.paused()
        per = fbgate.COSTS["schedule"]
        can = fbgate.affordable("user") // per
        if wait_min:
            raise RuntimeError(
                f"Facebook đang giới hạn lượt gọi API ({fbgate.gate.cooldown_reason or 'đã chạm giới hạn'}): app dừng mọi lệnh gọi Facebook để không bị chặn lâu hơn. "
                f"Thử lại sau khoảng {wait_min} phút."
            )
        if can <= 0:
            raise RuntimeError(f"Mỗi video hẹn giờ tốn {per} lượt gọi Facebook, chưa hẹn gì. " + (fbgate.why_not(per) or "Thử lại sau ít phút."))
        if len(folders) > can:
            job.log(
                f"Giới hạn lượt gọi Facebook: còn {fbgate.affordable('user')} lượt trong giờ này (mỗi video tốn {per} lượt) nên lần này chỉ xếp {can}/{len(folders)} video, "
                "phần còn lại để lần sau."
            )
            skipped_left += len(folders) - can
            folders = folders[:can]
    total = len(folders)
    existing = planner.existing_times(page_id, tz, since=datetime.now(tz) - timedelta(days=1))
    if mode == "auto":
        times = planner.plan(planner.rules_of(page), total, first, tz, existing, partial=partial) if total else []
        if len(times) < total:   # chỉ xảy ra với partial: các video đầu danh sách (theo thứ tự đăng) được xếp, phần cuối để lần sau
            left = total - len(times)
            job.log(f"Chỉ đủ chỗ trống cho {len(times)}/{total} video trong 29 ngày tới. {left} video còn lại giữ nguyên (chưa lên lịch), hãy lên lịch tiếp sau.")
            folders = folders[: len(times)]
            total = len(times)
            skipped_left += left
    else:
        times = [first + timedelta(hours=interval_hours * i) for i in range(total)]
        if total:
            last = times[-1]
            if last > datetime.now(tz) + timedelta(days=planner.MAX_DAYS):
                max_n = int((planner.MAX_DAYS * 24 - (first - datetime.now(tz)).total_seconds() / 3600) // interval_hours) + 1
                raise RuntimeError(
                    f"Video cuối cùng sẽ rơi vào {last:%Y-%m-%d %H:%M}, vượt giới hạn Facebook cho phép hẹn giờ (trong vòng 29 ngày). "
                    f"Hãy chọn ít video hơn (tối đa khoảng {max(max_n, 1)} video với khoảng cách này) hoặc giảm khoảng cách giờ."
                )
    job.set_progress(0, total)
    job.log(
        f"{total} video sẽ được {'xem trước' if dry_run else 'hẹn giờ'} trên Fanpage: {pages.label(page)} "
        f"({'tự xếp theo khung giờ của Page' if mode == 'auto' else f'cách nhau {interval_hours:g} giờ'})."
    )
    for w in planner.warnings(page, times, existing):
        job.log(f"CẢNH BÁO: {w}")
    done = 0

    for i, folder in enumerate(folders):
        if job.cancelled:
            job.log("Đã dừng theo yêu cầu.")
            break
        when = times[i]
        job.log(f"[{i + 1}/{total}] {when:%Y-%m-%d %H:%M} ({tz_name}) <- {folder.name}")
        if dry_run:
            job.set_progress(i + 1, total)
            continue
        try:
            video_id = schedule_reel(
                page_id, token, video_file(folder), library.build_caption(folder), int(when.timestamp())
            )
        except fbgate.RateLimited as exc:
            raise RuntimeError(
                f"Đã hẹn thành công {done}/{total} video trước khi dừng. {exc} "
                "Các video còn lại giữ nguyên (chưa lên lịch), hãy hẹn tiếp sau."
            ) from None
        except FacebookError as exc:
            hours = ratelimit.block_hours(exc.code, exc.subcode, exc.message)
            if hours:
                pages.mark_blocked(page_id, hours, str(exc))
                raise RuntimeError(
                    f"Facebook đang giới hạn tần suất đăng của Page này. Đã hẹn thành công {done}/{total} video trước khi bị chặn; "
                    f"app dừng lại để không bị chặn lâu hơn. Hãy đợi ít nhất {hours} giờ rồi hẹn tiếp (app sẽ nhắc ở Tổng quan và tab Cài đặt Page). "
                    f"Chi tiết từ Facebook: {exc}"
                ) from None
            raise
        (folder / "scheduled.json").write_text(
            json.dumps(
                {
                    "video_id": video_id,
                    "scheduled_for": when.isoformat(),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "page_id": page_id,
                    "page_name": pages.label(page),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        done += 1
        job.set_progress(i + 1, total)
        if i < total - 1:
            delay = eff["delay_seconds"]
            _pause(job, delay + random.uniform(0, delay / 2))

    bad_note = f" {invalid} video không đạt yêu cầu Reels nên đã bị bỏ qua (xem nhật ký)." if invalid else ""
    if dry_run:
        return "Xem trước xong, chưa đăng gì." + bad_note + (f" ({skipped_left} video sẽ chưa được xếp vì hết chỗ trống hoặc đạt giới hạn mỗi 24 giờ.)" if skipped_left else "")
    note = f" Còn {skipped_left} video chưa xếp (hết chỗ trống hoặc đạt giới hạn mỗi 24 giờ), hãy lên lịch tiếp sau." if skipped_left else ""
    return f"Đã hẹn giờ {done}/{total} video.{note}{bad_note}"
