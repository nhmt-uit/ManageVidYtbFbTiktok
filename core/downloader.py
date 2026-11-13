"""Tải video YouTube, TikTok (không logo) hoặc Rednote (Xiaohongshu) bằng yt-dlp.

Cấu trúc lưu:
  <OUTPUT_DIR>/<tên thư mục>/<ngày - tiêu đề [id]>/
      video.mp4, title.txt, description.txt, hashtags.txt, meta.json
  <OUTPUT_DIR>/<tên thư mục>/permission.json   (ghi nhận sự đồng ý của chủ kênh)
"""
from __future__ import annotations

import importlib.util
import json
import re
import random
import shutil
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse, urlunparse

from yt_dlp import YoutubeDL
from yt_dlp.networking import Request
from yt_dlp.utils import js_to_json

from . import config, library, linkfile, pages, reelcheck, removed, ytdlp_update

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


REDNOTE_HOSTS = ("xiaohongshu.com", "xhslink.com", "rednote.com")   # rednote.com = tên miền quốc tế, link chia sẻ từ web hay dùng
URL_RE = re.compile(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+", re.I)
MAX_URLS = 1000
REDNOTE_NOTE_RE = re.compile(r"^/(?:explore|discovery/item)/([0-9a-f]{16,32})/?$", re.I)
REDNOTE_PROFILE_NOTE_RE = re.compile(r"^/user/profile/[0-9a-f]+/([0-9a-f]{16,32})/?$", re.I)


def platform_of(url: str) -> str:
    """"youtube" | "tiktok" | "rednote" | "" theo tên miền của đường dẫn."""
    host = (urlparse((url or "").strip()).hostname or "").lower()
    if host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com"):
        return "youtube"
    if host == "tiktok.com" or host.endswith(".tiktok.com"):
        return "tiktok"
    if any(host == h or host.endswith("." + h) for h in REDNOTE_HOSTS):
        return "rednote"
    return ""


def validate_url(url: str) -> str:
    url = (url or "").strip()
    if urlparse(url).scheme not in ("http", "https") or not platform_of(url):
        raise ValueError("Chỉ hỗ trợ đường dẫn YouTube (youtube.com, youtu.be), TikTok (tiktok.com, vm.tiktok.com) hoặc Rednote (xiaohongshu.com, rednote.com, xhslink.com).")
    return url


def parse_urls(text: str) -> list[str]:
    """Lấy mọi đường dẫn trong đoạn chữ (mỗi dòng một link, hoặc dán nguyên đoạn "chia sẻ" của app), bỏ trùng, kiểm tra từng cái."""
    urls: list[str] = []
    for u in URL_RE.findall(text or ""):
        u = u.rstrip(".,;:!?)]}>")
        if u not in urls:
            urls.append(validate_url(u))
    if not urls:
        raise ValueError("Chưa có đường dẫn nào. Dán link kênh hoặc video (nhiều link thì mỗi dòng một link).")
    if len(urls) > MAX_URLS:
        raise ValueError(f"Nhiều quá: tối đa {MAX_URLS} đường dẫn mỗi lần.")
    return urls


def known_id(platform: str, url: str) -> str:
    """ID video đọc thẳng từ link MỘT video (không cần mạng) để bỏ qua link đã tải rồi mà không phải mở trang. Link kênh, danh sách, link rút gọn thì trả về chuỗi rỗng."""
    u = urlparse((url or "").strip())
    host = (u.hostname or "").lower()
    path = u.path or ""
    if platform == "youtube":
        if "list" in parse_qs(u.query):
            return ""   # link kèm danh sách phát: yt-dlp có thể tải cả danh sách
        if host == "youtu.be":
            m = re.match(r"^/([\w-]{11})/?$", path)
        elif path == "/watch":
            v = (parse_qs(u.query).get("v") or [""])[0]
            m = re.match(r"^([\w-]{11})$", v)
        else:
            m = re.match(r"^/(?:shorts|live|embed)/([\w-]{11})/?$", path)
        return m.group(1) if m else ""
    if platform == "tiktok":
        m = re.search(r"/video/(\d{15,20})", path)
        return m.group(1) if m else ""
    if platform == "rednote":
        m = RN_ID_RE.search(path) or REDNOTE_PROFILE_NOTE_RE.match(path)
        return m.group(1).lower() if m else ""
    return ""


CONTENT_CHOICES = ("all", "video", "images")   # Rednote: tải toàn bộ, chỉ video, hay chỉ ảnh


class _WrongType(Exception):
    """Bài không đúng loại đang chọn (ví dụ bài video khi chỉ tải ảnh): bỏ qua, không tính là lỗi."""


class _NoMedia(Exception):
    """Đã mở được bài nhưng bài không có video lẫn ảnh nào để tải: coi như link đã xong."""


class RednoteLogin(RuntimeError):
    """Rednote đòi đăng nhập/xác minh: dừng cả lượt tải ngay, mở tiếp dễ bị khoá tài khoản."""


RN_LOGIN_KEYS = ("login", "log in", "sign in", "登录", "登錄", "captcha", "verif", "验证", "驗證", "cookies")
RN_LOGIN_CODES = re.compile(r"(?<![0-9a-z])(?:461|471)(?![0-9a-z])")   # mã chặn của Rednote, đứng riêng (không phải một đoạn trong ID bài)
_URL_OR_ID_RE = re.compile(r"\S*://\S*|\b[0-9a-z]{16,}\b")


def rednote_needs_login(msg: str) -> bool:
    """Lỗi có phải Rednote đòi đăng nhập/xác minh không. Bỏ URL và ID bài trước khi dò: xsec_token hay ID có thể chứa "login", "461"..."""
    low = _URL_OR_ID_RE.sub(" ", (msg or "").lower())
    if "certificate" in low:   # lỗi chứng chỉ SSL (certificate verify failed) không phải đòi đăng nhập
        return False
    return any(k in low for k in RN_LOGIN_KEYS) or bool(RN_LOGIN_CODES.search(low))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def resolve_short(url: str) -> str:
    """Đổi link rút gọn xhslink.com (link chia sẻ từ app Rednote) thành link đầy đủ. Chỉ đi theo chuyển hướng tới xiaohongshu.com / xhslink.com."""
    opener = urllib.request.build_opener(_NoRedirect)
    cur = url
    for _ in range(5):
        if platform_of(cur) == "rednote" and "xhslink.com" not in (urlparse(cur).hostname or "").lower():
            return cur
        req = urllib.request.Request(cur, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17.0 Safari/605.1.15"})
        try:
            opener.open(req, timeout=15).close()
            break   # trả 200 mà không chuyển hướng: không có gì để đi tiếp
        except urllib.error.HTTPError as exc:
            loc = exc.headers.get("Location") if 300 <= exc.code < 400 else ""
            if not loc:
                break
            nxt = urljoin(cur, loc)
            if platform_of(nxt) != "rednote":
                break
            cur = nxt
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise RuntimeError("Không mở được link rút gọn Rednote (kiểm tra mạng): " + str(exc)[:120]) from None
    if platform_of(cur) == "rednote" and "xhslink.com" not in (urlparse(cur).hostname or "").lower():
        return cur
    raise RuntimeError("Không đổi được link rút gọn Rednote thành link bài viết. Hãy mở link trong trình duyệt rồi dán link ở thanh địa chỉ.")


def rednote_note_url(url: str) -> str:
    """Link bài Rednote chuẩn cho yt-dlp (www.xiaohongshu.com/explore/<id>, giữ xsec_token; link rednote.com được đổi sang tên miền này vì yt-dlp chỉ nhận xiaohongshu.com). Báo lỗi rõ nếu không phải link một bài."""
    u = urlparse(url)
    prof = REDNOTE_PROFILE_NOTE_RE.match(u.path)
    if prof or REDNOTE_NOTE_RE.match(u.path):
        path = f"/explore/{prof.group(1)}" if prof else u.path.rstrip("/")   # bài mở từ trang cá nhân: /user/profile/<uid>/<id> -> /explore/<id>
        return urlunparse(("https", "www.xiaohongshu.com", path, "", u.query, ""))
    if "/user/profile" in u.path:
        raise RuntimeError("Rednote chưa hỗ trợ tải theo trang cá nhân. Hãy dán link từng bài (mỗi dòng một link).")
    raise RuntimeError("Link Rednote này không phải một bài video (cần dạng xiaohongshu.com/explore/... hoặc /discovery/item/...).")


def normalize_url(url: str, kind: str) -> str:
    """Link kênh YouTube trơn (@tên, /channel/..) thì thêm /shorts hoặc /videos. Link TikTok giữ nguyên."""
    u = url.strip()
    if platform_of(u) == "youtube" and re.search(r"youtube\.com/(@[^/?#]+|(channel|c|user)/[^/?#]+)/?$", u):
        u = u.rstrip("/") + ("/shorts" if kind == "shorts" else "/videos")
    return u


def video_format(platform: str, max_height: int) -> dict:
    """Tùy chọn chọn định dạng video.

    - Chiều "cao" của video dọc (Shorts, TikTok, 1080x1920) lớn hơn cạnh ngắn, nên lọc height<=1080 sẽ lỡ chọn bản 480p.
      Sắp xếp theo res (cạnh ngắn) mới đúng: lấy bản tốt nhất không vượt max_height.
    - TikTok: loại hẳn các bản có logo (download_addr); chỉ nhận bản gốc không logo (play_addr).
    """
    if platform == "tiktok":
        fmt = "bv*[format_note!*=?watermarked]+ba/b[format_note!*=?watermarked]"
    else:
        fmt = "bv*+ba/b"
    return {"format": fmt, "format_sort": [f"res:{max_height}"]}


def entry_url(platform: str, entry: dict) -> str:
    """Đường dẫn đầy đủ của một video trong danh sách kênh."""
    vid = entry.get("id")
    if platform == "tiktok":
        for key in ("webpage_url", "url"):
            u = entry.get(key)
            if isinstance(u, str) and platform_of(u) == "tiktok" and "/video/" in u:
                return u
        return f"https://www.tiktok.com/@/video/{vid}"   # yt-dlp chỉ cần ID, tên người dùng để trống vẫn được
    if platform == "rednote":
        u = entry.get("webpage_url")   # giữ nguyên link gốc: xsec_token trong link có thể cần để mở bài
        if isinstance(u, str) and platform_of(u) == "rednote" and ("/explore/" in u or "/discovery/item/" in u):
            return u
        return f"https://www.xiaohongshu.com/explore/{vid}"
    return f"https://www.youtube.com/watch?v={vid}"


def _opts(extra: dict | None = None, platform: str = "youtube") -> dict:
    opts: dict = {"quiet": True, "no_warnings": True}
    if platform == "rednote":   # Rednote hay đòi đăng nhập: dùng phiên đăng nhập của bạn trên máy này (tên trình duyệt hoặc file cookies.txt)
        src = (config.get("REDNOTE_COOKIES_BROWSER") or "").strip()
        if src.startswith(("/", "~")):
            opts["cookiefile"] = str(Path(src).expanduser())
        elif src:
            opts["cookiesfrombrowser"] = (src,)
    elif platform != "tiktok":   # cookie trình duyệt hay làm TikTok lỗi, và TikTok công khai không cần
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


SOURCE_NAMES = {"youtube": "YouTube", "tiktok": "TikTok", "rednote": "Rednote"}
MP3_KBPS = "320"      # chất lượng MP3 khi chỉ tải âm thanh
MAX_FAIL_STREAK = 10   # từng này video liên tiếp lỗi thì dừng, tránh chạy mãi khi YouTube đang chặn
RN_FAIL_STREAK = 3     # Rednote đòi đăng nhập/xác minh thì dừng sớm: cứ mở tiếp là dễ bị khóa tài khoản
RN_OPEN_GAP = (1.0, 2.5)   # nghỉ (giây) giữa hai lần mở trang bài Rednote khi gom danh sách


def fail_limit(platform: str) -> int:
    return RN_FAIL_STREAK if platform == "rednote" else MAX_FAIL_STREAK


# ---------- Bài Rednote chỉ có ảnh (không có video): lưu ảnh vào thư mục ----------
IMAGE_HOSTS = ("xhscdn.com", "xhscdn.net", "xiaohongshu.com")   # chỉ tải ảnh từ CDN của Rednote
MAX_IMAGES = 60
MAX_IMAGE_BYTES = 40 * 1024 * 1024
RN_ID_RE = re.compile(r"/(?:explore|discovery/item)/([0-9a-f]{16,32})", re.I)
IMAGE_EXT = {"image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif", "image/avif": "avif", "image/heic": "heic"}


def parse_rednote_note(html: str, note_id: str) -> dict | None:
    """Đọc thông tin bài từ window.__INITIAL_STATE__ của trang Rednote."""
    m = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*</script>", html or "", re.S)
    if not m:
        return None
    try:
        state = json.loads(js_to_json(m.group(1)))
        note = state["note"]["noteDetailMap"][note_id]["note"]
    except (ValueError, KeyError, TypeError):
        return None
    return note if isinstance(note, dict) else None


def rednote_image_urls(note: dict) -> list[str]:
    urls: list[str] = []
    for img in (note.get("imageList") or [])[:MAX_IMAGES]:
        if not isinstance(img, dict):
            continue
        cand = [img.get("urlDefault"), img.get("urlPre")] + [i.get("url") for i in (img.get("infoList") or []) if isinstance(i, dict)]
        for u in cand:
            host = (urlparse(u).hostname or "").lower() if isinstance(u, str) else ""
            if host and any(host == h or host.endswith("." + h) for h in IMAGE_HOSTS):
                urls.append(u if u.startswith("http") else "https:" + u)
                break
    return urls


def _read_limited(resp, limit: int) -> bytes:
    data = resp.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError("Tệp quá lớn, bỏ qua.")
    return data


def save_rednote_images(job, opts: dict, url: str, note_id: str, channel_dir: Path) -> tuple[Path, int, bool]:   # raises _WrongType nếu bài là video
    """Tải toàn bộ ảnh của một bài Rednote vào <thư mục kênh>/<ngày - tiêu đề [id]>/images/. Trả về (thư mục, số ảnh, thư mục mới tạo)."""
    headers = {"Referer": "https://www.xiaohongshu.com/"}
    with YoutubeDL(opts) as ydl:   # dùng chung cookie đăng nhập và bộ gọi mạng của yt-dlp
        resp = ydl.urlopen(Request(url, headers=headers))
        final = urlparse(str(getattr(resp, "url", "") or "")).path.lower()
        if any(k in final for k in ("login", "captcha", "verify", "website-login")):   # bị chuyển sang trang đăng nhập/xác minh
            raise RednoteLogin("Rednote chuyển sang trang đăng nhập/xác minh (login).")
        html = _read_limited(resp, 8 * 1024 * 1024).decode("utf-8", "replace")
        note = parse_rednote_note(html, note_id)
        if note is None:
            raise RuntimeError("Không đọc được bài này (Rednote có thể đòi đăng nhập hoặc xác minh, hoặc đã xóa bài). Đăng nhập Rednote trên trình duyệt đã đặt ở Cài đặt chung và thử lại.")
        if note.get("type") == "video" or note.get("video"):   # bài video có imageList nhưng đó chỉ là ảnh bìa
            raise _WrongType("bài video")
        urls = rednote_image_urls(note)
        if not urls:
            raise _NoMedia("Bài này không có video và cũng không có ảnh tải được.")
        ts = note.get("time")
        date = datetime.fromtimestamp(ts / 1000).strftime("%Y%m%d") if isinstance(ts, (int, float)) and ts > 0 else datetime.now().strftime("%Y%m%d")
        title = str(note.get("title") or note.get("displayTitle") or "").strip()
        folder = channel_dir / f"{date} - {safe_name(title or note_id)} [{note_id}]"
        created = not folder.exists()
        img_dir = folder / "images"
        img_dir.mkdir(parents=True, exist_ok=True)
        try:
            for i, u in enumerate(urls, 1):
                if job.cancelled:
                    raise RuntimeError("Đã dừng theo yêu cầu.")
                resp = ydl.urlopen(Request(u, headers=headers))
                ctype = str(resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                if not ctype.startswith("image/"):
                    raise RuntimeError(f"Ảnh {i} không phải tệp ảnh (nhận {ctype or 'không rõ'}).")
                data = _read_limited(resp, MAX_IMAGE_BYTES)
                (img_dir / f"{i:02d}.{IMAGE_EXT.get(ctype, 'jpg')}").write_bytes(data)
        except Exception:
            if created:
                shutil.rmtree(folder, ignore_errors=True)
            else:
                shutil.rmtree(img_dir, ignore_errors=True)
            raise
        desc = str(note.get("desc") or "")
        tags = ["#" + str(t.get("name")) for t in (note.get("tagList") or []) if isinstance(t, dict) and t.get("name")]
        (folder / "title.txt").write_text(title, encoding="utf-8")
        (folder / "description.txt").write_text(desc, encoding="utf-8")
        (folder / "hashtags.txt").write_text("\n".join(tags), encoding="utf-8")
        (folder / "meta.json").write_text(json.dumps({
            "id": note_id, "title": title, "platform": "rednote", "type": "images", "images": len(urls),
            "upload_date": date, "source_url": url,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    return folder, len(urls), created


def _image_ids(page_id: str) -> set:
    """ID các bài ảnh đã lưu (thư mục có images/) trong các thư mục của chính Page này (hoặc chưa thuộc Page nào nếu page_id trống)."""
    root = config.output_dir()
    ids: set = set()
    if not root.exists():
        return ids
    for ch in root.iterdir():
        if not ch.is_dir() or library.owner_of(ch) != page_id:
            continue
        for d in ch.iterdir():
            if d.is_dir() and (d / "images").is_dir():
                vid = library.yt_id(d)
                if vid:
                    ids.add(vid)
    return ids


def _explain(platform: str, msg: str) -> str:
    """Đổi lỗi kỹ thuật của yt-dlp thành lời dễ hiểu cho các lỗi hay gặp."""
    low = msg.lower()
    if platform == "tiktok" and "requested format is not available" in low:
        return "TikTok chỉ trả bản có logo cho video này (không có bản gốc không logo). Đã bỏ qua để không lẫn logo vào video."
    if platform == "rednote" and (rednote_needs_login(msg) or any(k in low for k in ("initial state", "403", "unable to extract"))):
        return ("Rednote đòi đăng nhập hoặc xác minh. Đăng nhập Rednote trên trình duyệt đã đặt ở Cài đặt chung (ô Rednote: cookie), "
                "mở thử bài đó trong trình duyệt rồi tải lại. Chi tiết: " + msg[:160])
    return msg


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


def run(job, url: str, folder_name: str, kind: str, limit: int, note: str, page_id: str = "", fmt: str = "video", content: str = "all", txt_paths=(), redownload_removed: bool = False) -> str:
    """txt_paths: các file .txt người dùng đã chọn; link nào xong (đã tải, đã có, bài không có gì để tải) thì xoá khỏi các file đó."""
    book = linkfile.LinkBook([txt_paths] if isinstance(txt_paths, str) else txt_paths)
    try:
        return _run(job, url, folder_name, kind, limit, note, page_id, fmt, content, book, redownload_removed)
    finally:
        book.report(job)   # danh sách link lỗi luôn được báo, kể cả khi dừng giữa chừng


def _run(job, url: str, folder_name: str, kind: str, limit: int, note: str, page_id: str, fmt: str, content: str, book, redownload_removed: bool = False) -> str:
    audio = fmt == "audio"   # chỉ tải âm thanh (MP3) thay vì video
    if content not in CONTENT_CHOICES:
        content = "all"   # chỉ áp dụng cho Rednote (bài có thể là video hoặc ảnh); YouTube và TikTok bỏ qua lựa chọn này
    urls = parse_urls(url)
    if page_id and not pages.get(page_id):   # page_id trống = tải không gắn Fanpage (thư mục chưa thuộc Page nào)
        raise RuntimeError("Không tìm thấy Fanpage này. Chọn lại Fanpage rồi tải video.")
    root = config.output_dir()
    root.mkdir(parents=True, exist_ok=True)

    hint = ytdlp_update.stale_hint()
    if hint:
        job.log("Lưu ý: " + hint)
    if any(platform_of(u) == "tiktok" for u in urls) and importlib.util.find_spec("curl_cffi") is None:
        job.log("Lưu ý: TikTok cần thư viện curl-cffi để tải ổn định. Cài bằng: pip install \"yt-dlp[default,curl-cffi]\" rồi chạy lại ./service.sh restart.")
    if any(platform_of(u) == "rednote" for u in urls) and not (config.get("REDNOTE_COOKIES_BROWSER") or "").strip():
        job.log("Lưu ý: chưa đặt cookie đăng nhập cho Rednote (Cài đặt chung). Bài nào Rednote đòi đăng nhập sẽ bị lỗi.")

    # video đã có ở một thư mục của chính Page này (theo ID video) thì không tải lại.
    # Tải không gắn Page (page_id trống): chỉ đối chiếu với các thư mục cũng chưa thuộc Page nào
    have = {
        vid: [d for d in dirs if library.owner_of(d.parent) == page_id]
        for vid, dirs in library.id_index().items()
    }
    have = {vid: dirs for vid, dirs in have.items() if dirs}
    video_dirs = have   # ID -> thư mục video.mp4 của Page (MP3 của video đã tải sẽ vào đúng thư mục này)
    if audio:   # với MP3, "đã có" nghĩa là đã có file audio.mp3 (không phụ thuộc video.mp4)
        have = {vid: [] for vid in _audio_ids(page_id)}
    what = "MP3" if audio else "video"
    img_have = set() if audio else _image_ids(page_id)   # bài ảnh Rednote đã lưu
    gone = {} if redownload_removed else removed.ids()   # video đã tải rồi xoá (thư mục không còn): mặc định không tải lại
    n_gone = 0

    ok = skipped = failed = n_images_notes = empty = 0
    fail_streak = 0
    bad_links = filtered = 0
    bad_streak = 0   # số link liên tiếp không mở được
    halt = ""        # có lý do dừng (nhiều link liên tiếp lỗi) thì không mở thêm link nào nữa
    opened_rn = False
    seen_ids: set = set()
    done_ids: set = set()            # video đã xong trong lượt này (tải xong, đã có, bài không có gì để tải)
    id_links: dict = {}              # ID video -> mọi link một-video trỏ tới nó (cùng video có thể có nhiều dạng link)
    first_listing: dict | None = None
    first_platform = platform_of(urls[0])

    def stop_now(msg: str) -> None:
        nonlocal halt
        halt = msg
        job.log(halt)
        try:
            from . import notify
            notify.send("Tải video bị dừng", f"{pages.label(pages.get(page_id)) if page_id else 'Tải không gắn Page'}: {halt}", key=f"dlfail:{page_id}", ttl_hours=6)
        except Exception:  # noqa: BLE001
            pass

    def finish_id(vid, src, fresh: bool = False) -> None:
        """Video `vid` đã xong: xoá mọi link trỏ tới nó khỏi file. fresh = vừa tải về (nếu từng bị xoá thì bỏ khỏi sổ đã xoá)."""
        if fresh and vid and redownload_removed:
            try:
                removed.forget(vid)
            except OSError:
                pass
        if vid:
            done_ids.add(vid)
            for link in id_links.pop(vid, []):
                book.mark_done(link)
        book.mark_done(src)

    def login_halt() -> None:
        stop_now("Dừng ngay vì Rednote đòi đăng nhập hoặc xác minh. Mở Rednote trong trình duyệt đã đặt ở Cài đặt chung, đăng nhập (và làm xác minh nếu có), đợi một lúc rồi tải lại; các link chưa xong vẫn giữ trong file.")

    def take_url(u0: str) -> list:
        """Mở một đường dẫn và trả về các video MỚI trong đó: [(nền tảng, thông tin video)]. Link một video đã tải rồi thì bỏ qua ngay, không mở trang."""
        nonlocal first_listing, bad_links, filtered, skipped, bad_streak, halt, opened_rn, n_gone
        pf = platform_of(u0)
        kid = known_id(pf, u0)
        if kid and kid in gone and not (kid in have or kid in img_have):
            n_gone += 1
            job.log(f"Bỏ qua ({removed.note(gone.get(kid))}): {u0}")
            book.mark_done(u0)
            return []
        if kid and (kid in have or kid in img_have or kid in done_ids):
            skipped += 1
            job.log(f"Bỏ qua (đã tải rồi): {u0}")
            book.mark_done(u0)
            return []
        u1 = u0
        try:
            u1 = normalize_url(u0, kind)
            if pf == "rednote":
                u1 = rednote_note_url(resolve_short(u1) if "xhslink.com" in (urlparse(u1).hostname or "") else u1)
            if pf == "rednote":
                if opened_rn:
                    time.sleep(random.uniform(*RN_OPEN_GAP))   # đừng mở dồn dập
                opened_rn = True
            job.log(f"Lấy danh sách video: {u1}")
            nid0 = RN_ID_RE.search(urlparse(u1).path or "") if pf == "rednote" else None
            if nid0 and content == "images":   # chỉ ảnh: không cần yt-dlp (bài video sẽ được nhận ra và bỏ qua khi mở trang bài)
                listing = {"id": nid0.group(1), "webpage_url": u1, "_images": True}
            else:
                with YoutubeDL(_opts({"extract_flat": True, "skip_download": True}, pf)) as ydl:
                    listing = ydl.extract_info(u1, download=False)
        except Exception as exc:  # noqa: BLE001
            nid = RN_ID_RE.search(urlparse(u1).path or "") if pf == "rednote" else None
            if nid and "no video formats" in str(exc).lower():   # bài Rednote chỉ có ảnh: yt-dlp không có gì để tải, app tự lưu ảnh
                if content == "video":
                    filtered += 1
                    job.log(f"Bỏ qua (bài chỉ có ảnh, đang chọn chỉ video): {u1}")
                    return []
                job.log("Bài này không có video (chỉ có ảnh), app sẽ lưu ảnh.")
                listing = {"id": nid.group(1), "webpage_url": u1, "_images": True}
            else:
                bad_links += 1
                bad_streak += 1
                why = _explain(pf, str(exc))
                book.mark_error(u0, why)
                if len(urls) == 1:
                    raise RuntimeError(why) from exc
                job.log(f"Bỏ qua link lỗi {u0}: {why}")
                if pf == "rednote" and rednote_needs_login(str(exc)):
                    login_halt()
                elif bad_streak >= fail_limit(pf):
                    stop_now(f"Dừng vì {bad_streak} link liên tiếp không mở được ({SOURCE_NAMES[pf]} có thể đang đòi đăng nhập/xác minh hoặc chặn). Mở thử một bài trong trình duyệt, đợi một lúc rồi tải lại; các link chưa mở được giữ nguyên để thử lại.")
                return []
        bad_streak = 0
        if first_listing is None:
            first_listing = listing
        single = listing.get("entries") is None   # link một bài/video: kết quả của bài đó là kết quả của link
        src = u0 if single else None               # link kênh/danh sách: không xoá khỏi file (còn video khác chưa tải)
        es = [listing] if single else list(_flatten(listing["entries"]))
        out = []
        for e in es:
            if not (e and e.get("id")):
                continue
            if e["id"] in seen_ids:   # cùng video đã gặp ở link khác: xong video đó thì link này cũng xong
                if e["id"] in done_ids:
                    book.mark_done(src)
                elif src:
                    id_links.setdefault(e["id"], []).append(src)
                continue
            seen_ids.add(e["id"])
            if e["id"] in have or e["id"] in img_have:
                skipped += 1
                finish_id(e["id"], src)
            elif e["id"] in gone:
                n_gone += 1
                job.log(f"Bỏ qua ({removed.note(gone.get(e['id']))}): {entry_url(pf, e)}")
                finish_id(e["id"], src)
            else:
                out.append((pf, e, src))
        return out

    # Có giới hạn số video: chỉ mở link cho đến khi đủ số video MỚI; link còn lại để dành, mở tiếp khi có video lỗi và còn thiếu
    pending = list(urls)

    def fill(want: int) -> list:
        got: list = []
        while pending and not halt and (want <= 0 or len(got) < want):
            got += take_url(pending.pop(0))
        return got

    fresh = fill(limit if limit > 0 else 0)
    if first_listing is None:
        if halt:
            raise RuntimeError(halt)
        if n_gone and not skipped:
            return f"Không có video mới để tải: {n_gone} video đã tải và xoá trước đây (xem nhật ký). Muốn tải lại thì tick ô \"Tải lại cả video đã xoá trước đây\"." + (f" {bad_links} link không lấy được." if bad_links else "")
        if skipped:
            return f"Không có video mới để tải: {skipped} link đã tải rồi" + (f", {n_gone} video đã xoá trước đây" if n_gone else "") + (f", {bad_links} link không lấy được" if bad_links else "") + "."
        raise RuntimeError("Không lấy được video nào từ các đường dẫn đã dán.")
    listing = first_listing
    url = urls[0] if len(urls) == 1 else f"{urls[0]} (+{len(urls) - 1} link)"

    name = safe_name(
        folder_name or ("Rednote" if first_platform == "rednote" else "") or listing.get("uploader") or listing.get("channel") or listing.get("title") or "unnamed"
    )
    channel_dir = root / name
    cur_owner = library.owner_of(channel_dir) if channel_dir.exists() else ""
    if cur_owner and cur_owner != page_id:
        other = pages.get(cur_owner)
        raise RuntimeError(
            f'Thư mục "{name}" đang thuộc Page "{pages.label(other) if other else cur_owner}". '
            + ("Hãy vào Page đó để tải thêm vào thư mục này, hoặc đặt tên thư mục khác." if not page_id else "Mỗi thư mục chỉ thuộc một Page: hãy đặt tên thư mục khác cho Page này.")
        )
    channel_dir.mkdir(parents=True, exist_ok=True)
    if page_id and not cur_owner:
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

    # "Số video" là số video MỚI cần tải: video đã có không được tính vào số này
    target = (limit if pending else min(limit, len(fresh))) if limit > 0 else len(fresh)
    job.log(
        f"Đã xem {len(fresh) + skipped} video, trong đó {skipped} video đã có {what} (bỏ qua), {len(fresh)} video mới"
        + (f"; còn {len(pending)} link chưa mở (mở tiếp khi cần). " if pending else ". ")
        + (f"Sẽ tải {target} {what} mới." if target else f"Không có video mới để tải {what}.")
        + f" Lưu vào: {channel_dir}"
    )
    job.set_progress(0, target)

    def feed():
        """Các video mới theo thứ tự; link để dành chỉ được mở khi video trước đã xử lý xong mà vẫn chưa đủ số cần tải."""
        yield from fresh
        while pending and not halt:
            if job.cancelled or (target and ok >= target) or fail_streak >= fail_limit(first_platform):
                return
            yield from fill(max(1, target - ok))

    source = SOURCE_NAMES[first_platform]
    for i, (platform, entry, src) in enumerate(feed(), 1):
        source = SOURCE_NAMES[platform]
        if halt:
            break
        if job.cancelled:
            job.log("Đã dừng theo yêu cầu.")
            break
        if ok >= target:
            break
        if fail_streak >= fail_limit(platform):
            job.log(f"Dừng vì {fail_limit(platform)} video liên tiếp bị lỗi ({source} có thể đang chặn). Thử lại sau.")
            try:
                from . import notify
                notify.send("Tải video bị dừng", f"{pages.label(pages.get(page_id)) if page_id else 'Tải không gắn Page'}: {fail_limit(platform)} video liên tiếp bị lỗi, {source} có thể đang chặn. Thử lại sau. {hint}".strip(), key=f"dlfail:{page_id}", ttl_hours=6)
            except Exception:  # noqa: BLE001
                pass
            break
        vid = entry.get("id")
        video_url = entry_url(platform, entry)
        created_dir = None
        try:
            if entry.get("_images"):   # bài Rednote chỉ có ảnh
                if audio:
                    skipped += 1
                    job.log(f"Bỏ qua (bài chỉ có ảnh, không có âm thanh): {video_url}")
                    continue
                try:
                    folder, n_img, _created = save_rednote_images(job, _opts({}, platform), video_url, vid, channel_dir)
                except _WrongType:
                    if content != "images":   # "Toàn bộ": bài video mà yt-dlp không lấy được video là lỗi, không phải "không đúng loại"
                        raise RuntimeError("Bài này là video nhưng không lấy được video (Rednote có thể đòi đăng nhập hoặc giới hạn bài).")
                    filtered += 1
                    job.log(f"Bỏ qua (bài video, đang chọn chỉ ảnh): {video_url}")
                    continue
                except _NoMedia as exc:
                    empty += 1
                    fail_streak = 0
                    job.log(f"Bỏ qua ({exc}): {video_url}")
                    finish_id(vid, src)
                    continue
                n_images_notes += 1
                ok += 1
                fail_streak = 0
                finish_id(vid, src, fresh=True)
                job.log(f"[{ok}/{target}] Xong (bài ảnh, {n_img} ảnh): {folder.name}/images")
                job.set_progress(ok, target)
                if ok < target:
                    time.sleep(random.uniform(sleep_min, sleep_max))
                continue
            with YoutubeDL(_opts({"skip_download": True}, platform)) as ydl:
                info = ydl.extract_info(video_url, download=False)

            date = info.get("upload_date") or ("00000000" if platform == "youtube" else datetime.now().strftime("%Y%m%d"))   # Rednote không trả ngày đăng: dùng ngày tải
            existing = video_dirs.get(info["id"]) if audio else None
            if existing:   # video đã tải trước đó (kể cả khi tiêu đề trên YouTube đã đổi): đặt MP3 vào cùng thư mục
                folder = existing[0]
            else:
                folder = channel_dir / f"{date} - {safe_name(info.get('title', ''))} [{info['id']}]"
            out_file = folder / ("audio.mp3" if audio else "video.mp4")
            if out_file.exists():
                skipped += 1
                job.log(f"[{ok}/{target}] Bỏ qua (đã có): {folder.name}")
                finish_id(vid, src)
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
                    },
                    platform,
                )
            else:
                dl_opts = _opts(
                    {
                        **video_format(platform, max_height),
                        "merge_output_format": "mp4",
                        "outtmpl": str(folder / "video.%(ext)s"),
                        "sleep_interval": sleep_min,
                        "max_sleep_interval": sleep_max,
                    },
                    platform,
                )
            with YoutubeDL(dl_opts) as ydl:
                ydl.download([video_url])
            if not out_file.exists():
                raise RuntimeError(f"Không thấy file {out_file.name} sau khi tải (thiếu ffmpeg hoặc {source} trả về định dạng lạ).")

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
                            "platform": platform,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            ok += 1
            fail_streak = 0
            finish_id(vid, src, fresh=True)
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
            if job.cancelled:   # bấm Dừng giữa lúc tải: không phải lỗi của link, link giữ nguyên trong file
                if created_dir is not None:
                    shutil.rmtree(created_dir, ignore_errors=True)
                job.log("Đã dừng theo yêu cầu.")
                break
            failed += 1
            fail_streak += 1
            msg = _explain(platform, str(exc))
            job.log(f"Lỗi {vid}: {msg}")
            book.mark_error(src or video_url, msg)
            if created_dir is not None:
                shutil.rmtree(created_dir, ignore_errors=True)   # dọn thư mục vừa tạo mà tải không thành công
            if platform == "rednote" and (isinstance(exc, RednoteLogin) or rednote_needs_login(str(exc))):
                login_halt()
        job.set_progress(ok, target)

    return f"Tải xong {ok}{' MP3' if audio else ''}, bỏ qua {skipped}" + (f" (và {n_gone} video đã xoá trước đây)" if n_gone else "") + f", lỗi {failed}. Thư mục: {name}" + (f" Trong đó {n_images_notes} bài chỉ có ảnh (lưu ở thư mục images của từng bài)." if n_images_notes else "") + (f" Có {bad_links} link không lấy được." if bad_links else "") + (f" {empty} bài không có video/ảnh nào để tải." if empty else "") + (f" Danh sách {len(book.errors)} link lỗi ở cuối nhật ký." if book.errors else "") + (f" Bỏ qua {filtered} bài không đúng loại đã chọn." if filtered else "") + (" " + halt if halt else "")
