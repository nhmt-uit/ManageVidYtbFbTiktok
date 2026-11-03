"""Tải video YouTube bằng yt-dlp.

Cấu trúc lưu:
  <OUTPUT_DIR>/<tên thư mục>/<ngày - tiêu đề [id]>/
      video.mp4, title.txt, description.txt, hashtags.txt, meta.json
  <OUTPUT_DIR>/<tên thư mục>/permission.json   (ghi nhận sự đồng ý của chủ kênh)
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from urllib.parse import urlparse

from yt_dlp import YoutubeDL

from . import config, library, pages, reelcheck, ytdlp_update

HASHTAG_RE = re.compile(r"#\w+", re.UNICODE)


def safe_name(text: str, max_len: int = 80) -> str:
    text = re.sub(r'[\\/:*?"<>|\r\n\t]', " ", text or "")
    text = re.sub(r"\s+", " ", text).strip().strip(".")
    return text[:max_len].strip() or "untitled"


def extract_hashtags(info: dict) -> list[str]:
    tags: list[str] = []
    for source in (info.get("title") or "", info.get("description") or ""):
        tags += HASHTAG_RE.findall(source)
    tags += ["#" + t.replace(" ", "") for t in (info.get("tags") or [])]
    seen, result = set(), []
    for t in tags:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            result.append(t)
    return result


def validate_url(url: str) -> str:
    url = (url or "").strip()
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not (
        host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")
    ):
        raise ValueError("Chỉ hỗ trợ đường dẫn YouTube (youtube.com hoặc youtu.be).")
    return url


def normalize_url(url: str, kind: str) -> str:
    """Link kênh trơn (@tên, /channel/..) thì thêm /shorts hoặc /videos."""
    u = url.strip()
    if re.search(r"youtube\.com/(@[^/?#]+|(channel|c|user)/[^/?#]+)/?$", u):
        u = u.rstrip("/") + ("/shorts" if kind == "shorts" else "/videos")
    return u


def _opts(extra: dict | None = None) -> dict:
    opts: dict = {"quiet": True, "no_warnings": True}
    browser = config.get("YTDLP_COOKIES_BROWSER")
    if browser:
        opts["cookiesfrombrowser"] = (browser,)
    if extra:
        opts.update(extra)
    return opts


def _flatten(entries):
    for e in entries or []:
        if not e:
            continue
        if e.get("entries"):
            yield from _flatten(e["entries"])
        else:
            yield e


MP3_KBPS = "320"      # chất lượng MP3 khi chỉ tải âm thanh
MAX_FAIL_STREAK = 10   # từng này video liên tiếp lỗi thì dừng, tránh chạy mãi khi YouTube đang chặn


def _audio_ids(page_id: str) -> set:
    """ID các video đã có file audio.mp3 trong thư mục của chính Page này."""
    root = config.output_dir()
    ids = set()
    if not root.exists():
        return ids
    for ch in root.iterdir():
        if not ch.is_dir() or library.owner_of(ch) != page_id:
            continue
        for d in ch.iterdir():
            if d.is_dir() and (d / "audio.mp3").exists():
                vid = library.yt_id(d)
                if vid:
                    ids.add(vid)
    return ids


def run(job, url: str, folder_name: str, kind: str, limit: int, note: str, page_id: str = "", fmt: str = "video") -> str:
    audio = fmt == "audio"   # chỉ tải âm thanh (MP3) thay vì video
    url = normalize_url(validate_url(url), kind)
    if not pages.get(page_id):
        raise RuntimeError("Chưa chọn Fanpage để lưu video. Vào một Page rồi tải video.")
    root = config.output_dir()
    root.mkdir(parents=True, exist_ok=True)

    hint = ytdlp_update.stale_hint()
    if hint:
        job.log("Lưu ý: " + hint)
    job.log(f"Lấy danh sách video: {url}")
    list_opts = _opts({"extract_flat": True, "skip_download": True})
    with YoutubeDL(list_opts) as ydl:
        listing = ydl.extract_info(url, download=False)

    if listing.get("entries") is not None:
        entries = list(_flatten(listing["entries"]))
    else:
        entries = [listing]

    name = safe_name(
        folder_name or listing.get("uploader") or listing.get("channel") or listing.get("title") or "unnamed"
    )
    channel_dir = root / name
    cur_owner = library.owner_of(channel_dir) if channel_dir.exists() else ""
    if cur_owner and cur_owner != page_id:
        other = pages.get(cur_owner)
        raise RuntimeError(
            f'Thư mục "{name}" đang thuộc Page "{pages.label(other) if other else cur_owner}". '
            "Mỗi thư mục chỉ thuộc một Page: hãy đặt tên thư mục khác cho Page này."
        )
    channel_dir.mkdir(parents=True, exist_ok=True)
    if not cur_owner:
        if any(v.is_dir() and (v / "video.mp4").exists() for v in channel_dir.iterdir()):
            raise RuntimeError(f'Thư mục "{name}" đã có video nhưng chưa gán Page. Gán Page cho thư mục ở trang Tổng quan trước, hoặc đặt tên thư mục khác.')
        library.set_owner(channel_dir, page_id)
    perm = channel_dir / "permission.json"
    if not perm.exists():
        perm.write_text(
            json.dumps(
                {
                    "source_url": url,
                    "note": note,
                    "confirmed_at": datetime.now().isoformat(timespec="seconds"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    sleep_min = int(config.get("DOWNLOAD_SLEEP_MIN"))
    sleep_max = int(config.get("DOWNLOAD_SLEEP_MAX"))
    max_height = int(config.get("DOWNLOAD_MAX_HEIGHT"))
    ok = skipped = failed = 0

    # video đã có ở một thư mục của chính Page này (theo ID YouTube) thì không tải lại
    have = {
        vid: [d for d in dirs if library.owner_of(d.parent) == page_id]
        for vid, dirs in library.id_index().items()
    }
    have = {vid: dirs for vid, dirs in have.items() if dirs}
    video_dirs = have   # ID -> thư mục video.mp4 của Page (MP3 của video đã tải sẽ vào đúng thư mục này)
    if audio:   # với MP3, "đã có" nghĩa là đã có file audio.mp3 (không phụ thuộc video.mp4)
        have = {vid: [] for vid in _audio_ids(page_id)}
    what = "MP3" if audio else "video"

    # "Số video" là số video MỚI cần tải: video đã có không được tính vào số này
    entries = [e for e in entries if e.get("id")]
    fresh = [e for e in entries if not (e.get("id") and e["id"] in have)]
    skipped = len(entries) - len(fresh)
    target = min(limit, len(fresh)) if limit > 0 else len(fresh)
    job.log(
        f"Kênh có {len(entries)} video, trong đó {skipped} video đã có {what} (bỏ qua), còn {len(fresh)} video mới. "
        + (f"Sẽ tải {target} {what} mới." if target else f"Không có video mới để tải {what}.")
        + f" Lưu vào: {channel_dir}"
    )
    job.set_progress(0, target)
    entries = fresh
    fail_streak = 0

    for i, entry in enumerate(entries, 1):
        if job.cancelled:
            job.log("Đã dừng theo yêu cầu.")
            break
        if ok >= target:
            break
        if fail_streak >= MAX_FAIL_STREAK:
            job.log(f"Dừng vì {MAX_FAIL_STREAK} video liên tiếp bị lỗi (YouTube có thể đang chặn). Thử lại sau.")
            try:
                from . import notify
                notify.send("Tải video bị dừng", f"{pages.label(pages.get(page_id))}: {MAX_FAIL_STREAK} video liên tiếp bị lỗi, YouTube có thể đang chặn. Thử lại sau. {hint}".strip(), key=f"dlfail:{page_id}", ttl_hours=6)
            except Exception:  # noqa: BLE001
                pass
            break
        vid = entry.get("id")
        video_url = f"https://www.youtube.com/watch?v={vid}"
        created_dir = None
        try:
            with YoutubeDL(_opts({"skip_download": True})) as ydl:
                info = ydl.extract_info(video_url, download=False)

            date = info.get("upload_date") or "00000000"
            existing = video_dirs.get(info["id"]) if audio else None
            if existing:   # video đã tải trước đó (kể cả khi tiêu đề trên YouTube đã đổi): đặt MP3 vào cùng thư mục
                folder = existing[0]
            else:
                folder = channel_dir / f"{date} - {safe_name(info.get('title', ''))} [{info['id']}]"
            out_file = folder / ("audio.mp3" if audio else "video.mp4")
            if out_file.exists():
                skipped += 1
                job.log(f"[{ok}/{target}] Bỏ qua (đã có): {folder.name}")
                continue
            if not folder.exists():
                created_dir = folder
            folder.mkdir(parents=True, exist_ok=True)

            if audio:
                dl_opts = _opts(
                    {
                        "format": "bestaudio/best",
                        "outtmpl": str(folder / "audio.%(ext)s"),
                        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": MP3_KBPS}],
                        "sleep_interval": sleep_min,
                        "max_sleep_interval": sleep_max,
                    }
                )
            else:
                dl_opts = _opts(
                    {
                        "format": f"bv*[height<={max_height}]+ba/b[height<={max_height}]",
                        "merge_output_format": "mp4",
                        "outtmpl": str(folder / "video.%(ext)s"),
                        "sleep_interval": sleep_min,
                        "max_sleep_interval": sleep_max,
                    }
                )
            with YoutubeDL(dl_opts) as ydl:
                ydl.download([video_url])
            if not out_file.exists():
                raise RuntimeError(f"Không thấy file {out_file.name} sau khi tải (thiếu ffmpeg hoặc YouTube trả về định dạng lạ).")

            if not existing:   # video đã tải trước đó thì giữ nguyên tiêu đề, mô tả, hashtag, meta
                (folder / "title.txt").write_text(info.get("title") or "", encoding="utf-8")
                (folder / "description.txt").write_text(info.get("description") or "", encoding="utf-8")
                (folder / "hashtags.txt").write_text("\n".join(extract_hashtags(info)), encoding="utf-8")
                (folder / "meta.json").write_text(
                    json.dumps(
                        {
                            "id": info.get("id"),
                            "title": info.get("title"),
                            "channel": info.get("uploader") or info.get("channel"),
                            "upload_date": info.get("upload_date"),
                            "duration": info.get("duration"),
                            "source_url": video_url,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            ok += 1
            fail_streak = 0
            job.log(f"[{ok}/{target}] Xong: {folder.name}" + (" (audio.mp3)" if audio else ""))
            if not audio and reelcheck.enabled():   # kiểm tra luôn video vừa tải có đạt yêu cầu Reels không
                try:
                    chk = reelcheck.ensure(folder)
                    if chk and chk["errors"]:
                        job.log("    Không đạt yêu cầu Reels (sẽ bị bỏ qua khi hẹn giờ): " + " ".join(chk["errors"]))
                    elif chk and chk["warnings"]:
                        job.log("    Lưu ý: " + " ".join(chk["warnings"]))
                except Exception:  # noqa: BLE001  kiểm tra chỉ để báo trước, không làm hỏng việc tải
                    pass
        except Exception as exc:  # noqa: BLE001  tiếp tục video kế tiếp
            failed += 1
            fail_streak += 1
            job.log(f"Lỗi {vid}: {exc}")
            if created_dir is not None:
                shutil.rmtree(created_dir, ignore_errors=True)   # dọn thư mục vừa tạo mà tải không thành công
        job.set_progress(ok, target)

    return f"Tải xong {ok}{' MP3' if audio else ''}, bỏ qua {skipped}, lỗi {failed}. Thư mục: {name}"
