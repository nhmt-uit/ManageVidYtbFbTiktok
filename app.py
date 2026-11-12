#!/usr/bin/env python3
"""Quản lý video: tải từ kênh YouTube đã được đồng ý, hẹn giờ đăng lên Fanpage Facebook.

Chạy:  ./run.sh   (hoặc: python app.py)  rồi mở http://127.0.0.1:5173
"""
from __future__ import annotations

import os
import threading
import webbrowser
from datetime import datetime

from flask import Flask, abort, jsonify, request, send_from_directory

from core import affiliate, commenter, editor, series, translate, config, downloader, fbgate, library, manage, notify, pages, planner, publish, reelcheck, scheduler, stats, stock, tokens, ytdlp_update
from core import videofile
from core.jobs import manager

config.load_env()

app = Flask(__name__, static_folder="static", static_url_path="/static")
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}


@app.before_request
def guard():
    # Chỉ nhận yêu cầu từ chính máy này, và yêu cầu ghi phải là JSON (chặn CSRF từ trang web khác)
    host = request.host.rsplit(":", 1)[0].strip("[]")
    if host not in ALLOWED_HOSTS:
        abort(403)
    if request.method in ("POST", "PUT", "DELETE") and not request.is_json and request.headers.get("X-Upload") != "1":
        abort(415)   # tải file lên dùng header X-Upload (trang web khác không gửi được header lạ nếu không qua CORS)


@app.after_request
def no_stale_ui(resp):
    # Giao diện (html/css/js) luôn được trình duyệt hỏi lại, tránh dùng bản cũ sau khi cập nhật app
    if request.path == "/" or request.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


def body() -> dict:
    """JSON gửi lên, luôn là dict (JSON dạng khác bị coi như rỗng)."""
    d = request.get_json(silent=True)
    return d if isinstance(d, dict) else {}


def err(msg: str, code: int = 400):
    return jsonify({"error": msg}), code


def manage_err(e: "manage.ManageError"):
    """Lỗi thao tác huỷ / đổi giờ -> phản hồi JSON. 409: Facebook từ chối; 429: đang bị giới hạn lượt gọi (chưa làm gì); 400: lỗi khác."""
    if isinstance(e, manage.RateLimited):
        return jsonify({"error": str(e), "rate_limited": True, "minutes": e.minutes, "app_limited": e.local}), 429
    return jsonify({"error": str(e), "refused": e.refused}), 409 if e.refused else 400


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# ---------- Thư viện ----------
@app.get("/api/library")
def api_library():
    """Thư viện của một Page (page_id) kèm danh sách thư mục chưa gán Page. Không truyền page_id = tất cả."""
    data = library.scan(request.args.get("page_id") or None)
    data["reelcheck"] = {"available": reelcheck.available(), "enabled": reelcheck.enabled()}
    return jsonify(data)


@app.post("/api/reelcheck")
def api_reelcheck():
    """Kiểm tra các video chưa lên lịch của một Page có đạt yêu cầu Reels không (chạy nền)."""
    d = body()
    page = pages.get(str(d.get("page_id") or ""))
    if page is None:
        return err("Chưa chọn Fanpage.")
    if not reelcheck.available():
        return err("Chưa cài ffprobe (đi kèm ffmpeg) nên không kiểm tra được. Cài ffmpeg rồi thử lại.")
    if manager.has_running("check", page["id"]):
        return err("Đang kiểm tra video của Page này, đợi nó xong.")
    job = manager.start("check", f"Kiểm tra video Reels: {pages.label(page)}", reelcheck.run_check, page["id"], bool(d.get("force")), page_id=page["id"])
    return jsonify({"job": job.id})


@app.post("/api/notify/test")
def api_notify_test():
    """Gửi thử một thông báo tới các kênh đã cấu hình (macOS, Telegram)."""
    if not notify.configured():
        return err("Chưa bật kênh thông báo nào. Bật thông báo macOS hoặc điền token bot và chat ID của Telegram, bấm Lưu rồi thử lại.")
    res = notify.deliver("Thử thông báo", "Nếu bạn thấy tin này thì thông báo sự cố đã hoạt động.")
    names = {"mac": "macOS", "telegram": "Telegram"}
    return jsonify({"ok": all(not v for v in res.values()), "results": {names.get(k, k): (v or "OK") for k, v in res.items()}})


@app.get("/api/ytdlp")
def api_ytdlp():
    """Phiên bản yt-dlp đang dùng, bản mới nhất đã biết và việc có cần khởi động lại app không."""
    return jsonify(ytdlp_update.status())


@app.post("/api/ytdlp/update")
def api_ytdlp_update():
    if manager.has_running("ytdlp"):
        return err("Đang cập nhật yt-dlp rồi.")
    if manager.has_running("download"):
        return err("Đang có tác vụ tải video chạy. Đợi tải xong rồi cập nhật yt-dlp.")
    job = manager.start("ytdlp", "Cập nhật yt-dlp", ytdlp_update.update_job)
    return jsonify({"ok": True, "job": job.id})


@app.post("/api/restart")
def api_restart():
    """Khởi động lại app (chỉ khi chạy nền bằng service.sh, launchd sẽ bật lại ngay)."""
    if not ytdlp_update.in_service():
        return err("App không chạy bằng service.sh nên không tự khởi động lại được. Bấm Ctrl+C rồi chạy lại ./run.sh.")
    if manager.busy():
        return err("Đang có tác vụ chạy. Đợi xong rồi khởi động lại.")

    def go():
        try:
            ytdlp_update.restart_now(manager)
        except RuntimeError:
            pass   # có tác vụ bắt đầu trong lúc chờ: bỏ qua, người dùng bấm lại sau

    threading.Timer(1.0, go).start()   # trả lời giao diện trước rồi mới thoát
    return jsonify({"ok": True})


@app.post("/api/notify/telegram-chat")
def api_notify_chat():
    """Tìm chat ID Telegram từ tin nhắn mới nhất gửi cho bot và lưu vào cài đặt."""
    found = notify.telegram_find_chat()
    if found.get("error"):
        return err(found["error"])
    config.update_env({"TELEGRAM_CHAT_ID": found["chat_id"]})
    return jsonify({"ok": True, **found})


@app.post("/api/channels/assign")
def api_channel_assign():
    d = body()
    try:
        return jsonify({"ok": True, **library.assign_channel(str(d.get("name") or ""), str(d.get("page_id") or ""))})
    except ValueError as e:
        return err(str(e))


@app.get("/api/overview")
def api_overview():
    """Tổng quan mọi Page: số video theo trạng thái, bài hôm nay, bài kế tiếp, mức dùng giới hạn 24 giờ, trạng thái bị chặn."""
    from datetime import timedelta
    scan = library.scan()
    by_owner: dict = {}
    for v in scan["videos"]:
        by_owner.setdefault(v["owner"], []).append(v)
    now = datetime.now().astimezone()
    out = []
    for p in pages.all_pages():
        eff = pages.effective(p)
        tz = pages.tz_of(p)
        local = now.astimezone(tz)
        day0 = local.replace(hour=0, minute=0, second=0, microsecond=0)
        day1 = day0 + timedelta(days=1)
        c = {"new": 0, "pending": 0, "published": 0, "problem": 0}
        today_n = today_done = 0
        upcoming = []
        for v in by_owner.get(p["id"], []):
            if not v["scheduled"]:
                c["new"] += 1
                continue
            if v["publish_status"] == "published":
                g = "published"
            elif v["publish_status"] in publish.BAD or v["overdue"]:
                g = "problem"
            else:
                g = "pending"
            c[g] += 1
            when = commenter._parse(v["scheduled"]) if v["scheduled"] != "?" else None
            if when is None or g == "problem":
                continue
            when = when.astimezone(tz)
            if day0 <= when < day1:
                today_n += 1
                if g == "published":
                    today_done += 1
            if g == "pending" and when > local:
                upcoming.append(when)
        rules = planner.rules_of(p)
        cap = eff["publish_limit_24h"]
        info = pages.public(p)
        info.update({
            "counts": c,
            "folders": sum(1 for i in scan["channel_info"] if i["owner"] == p["id"]),
            "videos": len(by_owner.get(p["id"], [])),
            "today": {"scheduled": today_n, "published": today_done, "per_day": planner.posts_per_day(rules) if rules["slots"] else 0},
            "next_post": min(upcoming).isoformat() if upcoming else "",
            "used_24h": len(scheduler.recent_created(p["id"])),
            "cap": cap,
            "stock": stock.page_stock(p, by_owner.get(p["id"], []), now),
        })
        out.append(info)
    return jsonify({"pages": out, "unassigned": scan["unassigned"]})


@app.get("/api/stats")
def api_stats():
    """Thống kê bài đăng của một Page. Chỉ đọc dữ liệu trong app, không gọi Facebook."""
    page = pages.get(request.args.get("page_id", ""))
    if page is None:
        return err("Chưa chọn Fanpage.")
    return jsonify(stats.page_stats(page))


@app.get("/api/tools/rednote-script")
def api_rednote_script():
    """Script gom link cả trang cá nhân Rednote (người dùng dán vào Console của Chrome). Chỉ trả file cố định trong thư mục tools."""
    resp = send_from_directory(os.path.join(app.root_path, "tools"), "rednote_collect_links.js", mimetype="text/plain", max_age=0)
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.post("/api/series/set")
def api_series_set():
    """Sửa tay phim/tập của video (khi tự nhận từ tiêu đề bị sai). name "" hoặc episode null = quay về tự nhận."""
    d = body()
    rels = d.get("rels")
    if not isinstance(rels, list) or not rels or len(rels) > 1000 or not all(isinstance(r, str) for r in rels):
        return err("Chưa chọn video.")
    set_name, set_episode = "name" in d, "episode" in d
    if not (set_name or set_episode):
        return err("Không có gì để sửa.")
    if set_episode and len(rels) != 1:
        return err("Số tập chỉ sửa cho từng video một.")
    try:
        folders = [library.resolve(r) for r in rels]
        for f in folders:
            series.write_override(f, d.get("name"), d.get("episode"), set_name, set_episode)
    except ValueError as e:
        return err(str(e), 400)
    return jsonify({"ok": True, "count": len(folders)})


@app.get("/media/<path:rel>")
def media(rel):
    """Phát video.mp4; thêm ?draft=1 để xem bản nháp chưa duyệt."""
    root = config.output_dir()
    try:
        folder = library.resolve(rel)
    except ValueError:
        abort(404)
    name = videofile.DRAFT if request.args.get("draft") == "1" else videofile.video_file(folder).name
    return send_from_directory(root, f"{rel}/{name}", conditional=True)


# ---------- Chỉnh sửa video: phiên âm, phụ đề, xuất bản 9:16 ----------
def _edit_rel(d: dict | None = None) -> str:
    return str((d if d is not None else request.args).get("rel", ""))


@app.get("/api/edit/status")
def api_edit_status():
    try:
        return jsonify(editor.status(_edit_rel()))
    except ValueError as e:
        return err(str(e), 404)


@app.post("/api/edit/transcribe")
def api_edit_transcribe():
    d = body()
    try:
        folder = library.resolve(_edit_rel(d))
    except ValueError as e:
        return err(str(e), 404)
    if manager.has_running("edit"):
        return err("Đang có một tác vụ chỉnh sửa khác chạy. Đợi nó xong rồi thử lại.", 409)
    t = editor.tools(refresh=True)
    for key in ("ffmpeg", "whisper"):
        if not t[key]["ok"]:
            return err(t[key]["problem"], 409)
    lang = str(d.get("lang") or "vi")
    job = manager.start("edit", f"Phiên âm: {folder.name}", editor.transcribe_job, _edit_rel(d), lang, str(d.get("source") or "auto"))
    return jsonify({"job": job.id})


@app.post("/api/edit/translate")
def api_edit_translate():
    d = body()
    try:
        folder = library.resolve(_edit_rel(d))
    except ValueError as e:
        return err(str(e), 404)
    if manager.has_running("edit"):
        return err("Đang có một tác vụ chỉnh sửa khác chạy. Đợi nó xong rồi thử lại.", 409)
    cfg = translate.settings()
    if not cfg["ok"]:
        return err(cfg["problem"], 409)
    job = manager.start("edit", f"Dịch phụ đề: {folder.name}", editor.translate_job, _edit_rel(d), str(d.get("to") or "vi"))
    return jsonify({"job": job.id})


@app.post("/api/edit/origsubs/detect")
def api_edit_origsubs_detect():
    d = body()
    try:
        folder = library.resolve(_edit_rel(d))
    except ValueError as e:
        return err(str(e), 404)
    if manager.has_running("edit"):
        return err("Đang có một tác vụ chỉnh sửa khác chạy. Đợi nó xong rồi thử lại.", 409)
    t = editor.tools(refresh=True)
    if not t["ffmpeg"]["ok"]:
        return err(t["ffmpeg"]["problem"], 409)
    job = manager.start("edit", f"Dò sub gốc: {folder.name}", editor.detect_origsubs_job, _edit_rel(d))
    return jsonify({"job": job.id})


@app.post("/api/edit/origsubs")
def api_edit_origsubs_save():
    d = body()
    try:
        return jsonify(editor.save_origsubs(_edit_rel(d), d))
    except ValueError as e:
        return err(str(e), 404)
    except editor.EditError as e:
        return err(str(e))


@app.post("/api/edit/audio/scan")
def api_edit_audio_scan():
    d = body()
    try:
        folder = library.resolve(_edit_rel(d))
    except ValueError as e:
        return err(str(e), 404)
    if manager.has_running("edit"):
        return err("Đang có một tác vụ chỉnh sửa khác chạy. Đợi nó xong rồi thử lại.", 409)
    t = editor.tools(refresh=True)
    if not t["ffmpeg"]["ok"]:
        return err(t["ffmpeg"]["problem"], 409)
    job = manager.start("edit", f"Phân tích âm thanh: {folder.name}", editor.scan_audio_job, _edit_rel(d))
    return jsonify({"job": job.id})


@app.post("/api/edit/hook/generate")
def api_edit_hook_generate():
    d = body()
    try:
        folder = library.resolve(_edit_rel(d))
    except ValueError as e:
        return err(str(e), 404)
    if manager.has_running("edit"):
        return err("Đang có một tác vụ chỉnh sửa khác chạy. Đợi nó xong rồi thử lại.", 409)
    if not editor.hooks.find_claude():
        return err("Chưa tìm thấy lệnh `claude` (Claude Code) trên máy. Cài Claude Code và đăng nhập, hoặc đặt CLAUDE_BIN trong .env.", 409)
    notes = str(d.get("notes") or "")[:400]
    job = manager.start("edit", f"Đề xuất hook: {folder.name}", editor.hook_generate_job, _edit_rel(d), notes)
    return jsonify({"job": job.id})


@app.post("/api/edit/hook")
def api_edit_hook_save():
    d = body()
    try:
        return jsonify(editor.save_hook(_edit_rel(d), d.get("text")))
    except ValueError as e:
        return err(str(e), 404)


@app.post("/api/translate/test")
def api_translate_test():
    """Dịch thử một câu bằng cấu hình đang lưu để kiểm tra khóa, địa chỉ và model."""
    cfg = translate.settings()
    if not cfg["ok"]:
        return err(cfg["problem"], 409)
    try:
        return jsonify({"ok": True, "sample": translate.test_connection(), "label": cfg["label"], "model": cfg["model"]})
    except translate.TranslateError as e:
        return err(str(e), 502)


@app.post("/api/edit/subs")
def api_edit_subs():
    d = body()
    try:
        return jsonify(editor.save_subs(_edit_rel(d), d.get("cues")))
    except ValueError as e:
        return err(str(e), 404)
    except editor.EditError as e:
        return err(str(e))


@app.post("/api/edit/voice")
def api_edit_voice_upload():
    """Tải file giọng đọc lên (nội dung file là thân yêu cầu, tên file ở ?name=, cần header X-Upload: 1)."""
    try:
        return jsonify(editor.save_voice(_edit_rel(), request.args.get("name", ""), request.stream, request.content_length))
    except ValueError as e:
        return err(str(e), 404)
    except editor.EditError as e:
        return err(str(e))


@app.delete("/api/edit/voice")
def api_edit_voice_delete():
    try:
        editor.remove_voice(_edit_rel(body()))
    except ValueError as e:
        return err(str(e), 404)
    except editor.EditError as e:
        return err(str(e), 409)
    return jsonify({"ok": True})


@app.post("/api/edit/render")
def api_edit_render():
    d = body()
    try:
        folder = library.resolve(_edit_rel(d))
    except ValueError as e:
        return err(str(e), 404)
    if manager.has_running("schedule"):
        return err("Đang hẹn giờ đăng video. Đợi xong rồi hãy xuất video (tránh đăng nhầm bản cũ).", 409)
    if editor.is_scheduled(folder):
        return err("Video này đã lên lịch (Facebook đã nhận bản cũ). Huỷ lịch trước, chỉnh sửa xong rồi hẹn lại.", 409)
    if manager.has_running("edit"):
        return err("Đang có một tác vụ chỉnh sửa khác chạy. Đợi nó xong rồi thử lại.", 409)
    t = editor.tools(refresh=True)
    if not t["ffmpeg"]["ok"]:
        return err(t["ffmpeg"]["problem"], 409)
    job = manager.start("edit", f"Xuất video đã chỉnh: {folder.name}", editor.render_job, _edit_rel(d), d.get("settings"))
    return jsonify({"job": job.id})


@app.post("/api/edit/discard")
def api_edit_discard():
    try:
        editor.discard(_edit_rel(body()))
    except ValueError as e:
        return err(str(e), 404)
    except editor.EditError as e:
        return err(str(e), 409)
    return jsonify({"ok": True})


@app.post("/api/edit/approve")
def api_edit_approve():
    """Duyệt bản nháp: nó thay thế video.mp4 (video cũ bị xoá hẳn)."""
    d = body()
    if d.get("confirm") is not True:   # chặn gọi nhầm: việc này không hoàn tác được
        return err("Cần xác nhận: video gốc sẽ bị xoá và thay bằng bản chỉnh sửa.", 400)
    if manager.has_running("schedule"):
        return err("Đang hẹn giờ đăng video. Đợi xong rồi hãy duyệt (tránh đăng nhầm bản cũ).", 409)
    try:
        msg = editor.approve(_edit_rel(d))
    except ValueError as e:
        return err(str(e), 404)
    except editor.EditError as e:
        return err(str(e), 409)
    return jsonify({"ok": True, "message": msg})


@app.get("/api/caption")
def api_get_text():
    try:
        return jsonify(library.get_text(request.args.get("rel", "")))
    except ValueError as e:
        return err(str(e), 404)


@app.put("/api/caption")
def api_save_text():
    data = body()
    try:
        # Chỉ đụng vào phần nào có trong yêu cầu (tránh ghi đè nhầm)
        if "caption" in data:
            library.save_text(data.get("rel", ""), data.get("caption", ""))
        if "comment" in data:
            commenter.save_video_comment(library.resolve(data.get("rel", "")), data.get("comment", ""))
    except ValueError as e:
        return err(str(e), 404)
    try:
        if "affiliate" in data:
            commenter.save_link(library.resolve(data.get("rel", "")), data.get("affiliate", ""))
    except ValueError as e:
        return err(str(e), 400)
    return jsonify({"ok": True})


# ---------- Comment tự động ----------
@app.get("/api/pages/<page_id>/comment-pool")
def api_get_comment_pool(page_id):
    if pages.get(page_id) is None:
        return err("Không tìm thấy Fanpage.", 404)
    return jsonify({"items": pages.read_pool(page_id)})


@app.put("/api/pages/<page_id>/comment-pool")
def api_save_comment_pool(page_id):
    if pages.get(page_id) is None:
        return err("Không tìm thấy Fanpage.", 404)
    items = body().get("items", [])
    if not isinstance(items, list):
        return err("items phải là danh sách.", 400)
    return jsonify({"ok": True, "items": pages.save_pool(page_id, items)})


@app.post("/api/affiliate-import")
def api_affiliate_import():
    text = body().get("csv", "")
    if not isinstance(text, str) or not text.strip():
        return err("File CSV trống.")
    if len(text) > 2_000_000:
        return err("File CSV quá lớn.")
    return jsonify({"ok": True, **affiliate.import_csv(text)})


@app.post("/api/status/check")
def api_status_check():
    """Hỏi Facebook trạng thái mọi video đã hẹn giờ của Page (trừ bài đã đăng), lần lượt từng video, chạy nền."""
    d = body()
    page_id = str(d.get("page_id") or "")
    page = pages.get(page_id) if page_id else None
    if page_id and not page:
        return err("Fanpage không tồn tại.", 404)
    if manager.has_running("status-check"):
        return err("Đang có một đợt kiểm tra trạng thái chạy. Xem tiến độ ở tab Nhật ký.")
    folders = commenter.pending_folders(page_id)
    if not folders:
        return jsonify({"ok": True, "job": None, "result": "Không có video nào cần kiểm tra (chưa có bài hẹn giờ, hoặc đều đã đăng)."})
    why = fbgate.why_not(1, "user", commenter.CHECK_RESERVE())
    if why:
        return err("Chưa kiểm tra gì. " + why, 429)
    label = pages.label(page) if page else "mọi Fanpage"
    job = manager.start("status-check", f"Kiểm tra trạng thái đăng: {len(folders)} video, {label}", commenter.check_many, folders, page_id=page_id)
    return jsonify({"ok": True, "job": job.id, "total": len(folders)})


@app.post("/api/reschedule")
def api_reschedule():
    try:
        commenter.reschedule(library.resolve(body().get("rel", "")))
    except ValueError as e:
        return err(str(e), 400)
    return jsonify({"ok": True})


@app.post("/api/sched/cancel")
def api_sched_cancel():
    """Huỷ lịch một bài chưa đăng: xóa bài hẹn trên Facebook rồi gỡ lịch trong app (video về "Chưa lên lịch")."""
    d = body()
    try:
        folder = library.resolve(d.get("rel", ""))
        msg = manage.cancel(folder, local_only=bool(d.get("local_only")))
    except manage.ManageError as e:
        return manage_err(e)
    except ValueError as e:
        return err(str(e), 404)
    return jsonify({"ok": True, "message": msg})


def _rels_arg(d: dict, limit: int = 300):
    """Danh sách video gửi lên: list chuỗi không rỗng, bỏ trùng, tối đa `limit`. Trả về (list, None) hoặc (None, lỗi)."""
    rels = d.get("rels")
    if not isinstance(rels, list) or not rels or not all(isinstance(r, str) and r for r in rels):
        return None, err("Chưa chọn video nào.")
    rels = list(dict.fromkeys(rels))
    if len(rels) > limit:
        return None, err(f"Mỗi lần chỉ xử lý tối đa {limit} video.")
    return rels, None


@app.post("/api/sched/cancel-many")
def api_sched_cancel_many():
    """Huỷ lịch nhiều bài chưa đăng của một Page (tác vụ nền, xem tiến độ ở nhật ký)."""
    d = body()
    page = pages.get(str(d.get("page_id") or ""))
    if not page:
        return err("Chưa chọn Fanpage.")
    rels, bad = _rels_arg(d)
    if bad:
        return bad
    if manager.has_running("cancel") or manager.has_running("schedule"):
        return err("Đang có tác vụ hẹn giờ hoặc huỷ lịch chạy. Đợi nó xong rồi thử lại.")
    local_only = bool(d.get("local_only"))
    why = "" if local_only else fbgate.why_not(1)
    if why:
        return err("Chưa huỷ gì. " + why, 429)
    job = manager.start("cancel", f"{'Gỡ lịch trong app' if local_only else 'Huỷ lịch'}: {len(rels)} video, {pages.label(page)}",
                        manage.cancel_many, page["id"], rels, local_only, page_id=page["id"])
    return jsonify({"ok": True, "job": job.id})


@app.post("/api/reschedule-many")
def api_reschedule_many():
    """Hẹn lại nhiều bài lỗi / không thấy trên Facebook: gỡ lịch cũ trong app để chọn lại và hẹn giờ (không gọi Facebook)."""
    d = body()
    page = pages.get(str(d.get("page_id") or ""))
    if not page:
        return err("Chưa chọn Fanpage.")
    rels, bad = _rels_arg(d)
    if bad:
        return bad
    if manager.has_running("cancel") or manager.has_running("schedule"):
        return err("Đang có tác vụ hẹn giờ hoặc huỷ lịch chạy. Đợi nó xong rồi thử lại.")
    done, failed = 0, []
    for rel in rels:
        try:
            folder = library.resolve(rel)
            owner = pages.resolve(commenter.read_sched(folder) or {})
            if owner is None or owner["id"] != page["id"]:
                raise ValueError("Video này không thuộc Fanpage đang chọn, hoặc chưa được hẹn giờ.")
            commenter.reschedule(folder)
            done += 1
        except ValueError as e:
            failed.append({"rel": rel, "error": str(e)})
    return jsonify({"ok": True, "done": done, "failed": failed})


@app.post("/api/sched/retime")
def api_sched_retime():
    """Đổi giờ đăng của một bài chưa đăng. Thử sửa trực tiếp trên Facebook; rebook=true: huỷ rồi hẹn lại (tải lại video)."""
    d = body()
    when = str(d.get("when") or "")
    try:
        folder = library.resolve(d.get("rel", ""))
        sched = commenter.read_sched(folder)
        page = pages.resolve(sched) if sched else None
        if page is None:
            return err("Video này chưa được hẹn giờ, hoặc Fanpage của nó đã bị xóa khỏi app.", 400)
        if not d.get("rebook"):
            return jsonify({"ok": True, "message": manage.retime(folder, when)})
        # Huỷ rồi hẹn lại: kiểm tra mọi điều kiện trước khi xóa bài cũ để không mất lịch mà không hẹn lại được
        manage.parse_when(page, when)
        if library.owner_of_video(d["rel"]) != page["id"]:
            return err("Video này không thuộc Fanpage của bài đã hẹn (thư mục đã đổi Page). Không hẹn lại tự động được.", 400)
        cap = pages.effective(page)["publish_limit_24h"]
        if cap and len(scheduler.recent_created(page["id"])) >= cap:
            return err(f"Page đã hẹn đủ {cap} video trong 24 giờ qua (giới hạn của Page), nên chưa hẹn lại được. Bài cũ chưa bị huỷ. Thử lại sau hoặc đổi giờ trực tiếp.", 400)
        if pages.blocked_until(page):
            return err("Facebook đang giới hạn tần suất đăng của Page này. Đợi hết rồi hẹn lại, hoặc bỏ cảnh báo ở Cài đặt Page.", 400)
        if manager.has_running("schedule"):
            return err("Đang có một tác vụ hẹn giờ chạy. Đợi nó xong rồi thử lại.", 400)
        why = fbgate.why_not(1 + fbgate.COSTS["schedule"] + 1)   # xoá bài cũ (+ kiểm tra giờ) rồi hẹn lại: đủ lượt gọi cho cả hai thì mới xoá
        if why:
            return err("Chưa huỷ gì. " + why, 429)
        rel = d["rel"]
        manage.cancel(folder)
        title = f"Hẹn lại: 1 video, {pages.label(page)}"
        job = manager.start("schedule", title, scheduler.run, page["id"], [rel], when, 6.0, pages.effective(page)["tz"], False, "interval", "oldest", False, page_id=page["id"])
        return jsonify({"ok": True, "job": job.id, "message": "Đã huỷ bài cũ, đang hẹn lại với giờ mới."})
    except manage.ManageError as e:
        return manage_err(e)
    except ValueError as e:
        return err(str(e), 404)


@app.post("/api/comment-now")
def api_comment_now():
    data = body()
    try:
        folder = library.resolve(data.get("rel", ""))
    except ValueError as e:
        return err(str(e), 404)
    status, message = commenter.process(commenter.worker_job, folder, force=True)
    return jsonify({"ok": status in ("posted", "done"), "status": status, "message": message})


# ---------- Quản lý Fanpage ----------
def _page_stats() -> dict:
    stats: dict = {}
    for folder in commenter.find_scheduled():
        sched = commenter.read_sched(folder)
        pg = pages.resolve(sched)
        if pg is None:
            continue
        st = stats.setdefault(pg["id"], {"scheduled": 0, "published": 0, "pending_comment": 0})
        st["scheduled"] += 1
        if sched.get("publish_status") == "published":
            st["published"] += 1
        if commenter.comment_status(folder, sched)[0] in ("pending", "retry"):
            st["pending_comment"] += 1
    return stats


@app.get("/api/pages")
def api_pages():
    tokens.fill_names()
    stats = _page_stats()
    out = []
    for p in pages.all_pages():
        info = pages.public(p)
        info.update(stats.get(p["id"], {"scheduled": 0, "published": 0, "pending_comment": 0}))
        out.append(info)
    return jsonify({"pages": out})


@app.post("/api/pages/discover")
def api_pages_discover():
    return jsonify(tokens.discover())


@app.post("/api/pages/add")
def api_pages_add():
    ids = body().get("ids", [])
    if not isinstance(ids, list) or not ids:
        return err("Chưa chọn Page nào.")
    added = pages.add_candidates([str(i) for i in ids])
    if not added:
        return err("Không thêm được. Bấm lại \"Lấy danh sách từ Facebook\" rồi chọn Page.")
    return jsonify({"ok": True, "added": added})


@app.put("/api/pages/<page_id>")
def api_page_update(page_id):
    d = body()
    try:
        rules = None
        if "schedule" in d:   # kiểm tra trước khi ghi bất cứ thứ gì
            if not isinstance(d["schedule"], dict):
                return err("Quy tắc đăng không hợp lệ.")
            cur = pages.get(page_id)
            if cur is None:
                return err("Không tìm thấy Fanpage.", 404)
            rules = planner.clean_rules({**planner.rules_of(cur), **d["schedule"]})   # trường nào không gửi thì giữ nguyên
        new_settings = None
        if "settings" in d:
            if not isinstance(d["settings"], dict):
                return err("Cài đặt Page không hợp lệ.")
            if pages.get(page_id) is None:
                return err("Không tìm thấy Fanpage.", 404)
            new_settings = pages.clean_settings(d["settings"])
        p = pages.rename_or_toggle(
            page_id,
            name=d.get("name") if "name" in d else None,
            auto_comment=d.get("auto_comment") if "auto_comment" in d else None,
        )
        if rules is not None:
            p = pages.set_schedule(page_id, rules)
        if new_settings is not None:
            p = pages.set_settings(page_id, new_settings)
    except KeyError:
        return err("Không tìm thấy Fanpage.", 404)
    except ValueError as e:
        return err(str(e))
    return jsonify({"ok": True, "page": pages.public(p)})


@app.delete("/api/pages/<page_id>/block")
def api_page_unblock(page_id):
    """Bỏ cảnh báo "Facebook đang giới hạn tần suất" khi bạn chắc chắn đã hết bị chặn."""
    try:
        p = pages.clear_blocked(page_id)
    except KeyError:
        return err("Không tìm thấy Fanpage.", 404)
    return jsonify({"ok": True, "page": pages.public(p)})


@app.delete("/api/pages/<page_id>")
def api_page_delete(page_id):
    try:
        pages.remove(page_id)
    except KeyError:
        return err("Không tìm thấy Fanpage.", 404)
    return jsonify({"ok": True})


@app.get("/api/pages/<page_id>/check")
def api_page_check(page_id):
    return jsonify(tokens.check_page(page_id))


# ---------- Lịch ----------
@app.get("/api/calendar")
def api_calendar():
    """Các bài đã hẹn trong khoảng ngày [start, start + days), theo múi giờ của Page. page_id rỗng = mọi Page (múi giờ Việt Nam)."""
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    page_id = request.args.get("page_id", "")
    cal_page = pages.get(page_id) if page_id else None
    try:
        tz = pages.tz_of(cal_page) if cal_page else ZoneInfo(pages.DEFAULT_TZ)
    except Exception:  # noqa: BLE001
        return err("Múi giờ của Page không hợp lệ. Sửa ở Cài đặt Page.")
    try:
        raw = request.args.get("start", "")
        if raw:
            start = datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=tz)
        else:   # không truyền: thứ Hai của tuần hiện tại
            today = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
            start = today - timedelta(days=today.weekday())
        days = min(max(int(request.args.get("days", 7)), 1), 42)
        end = start + timedelta(days=days)
    except (ValueError, OverflowError):
        return err("Ngày không hợp lệ.")
    items = []
    for v in library.scan()["videos"]:   # theo Page đã hẹn bài (không theo thư mục chứa video)
        if not v["scheduled"] or v["scheduled"] == "?" or (page_id and v["page_id"] != page_id):
            continue
        when = commenter._parse(v["scheduled"])
        if when is None:
            continue
        when = when.astimezone(tz)
        if start <= when < end:
            items.append({
                "rel": v["rel"], "title": v["title"], "when": when.isoformat(), "date": f"{when:%Y-%m-%d}", "time": f"{when:%H:%M}",
                "page_id": v["page_id"], "page_name": v["page_name"], "publish_status": v["publish_status"],
                "overdue": v["overdue"], "comment_status": v["comment_status"], "permalink": v["permalink"],
            })
    items.sort(key=lambda i: i["when"])
    return jsonify({"tz": str(tz), "today": f"{datetime.now(tz):%Y-%m-%d}", "start": f"{start:%Y-%m-%d}", "days": days, "items": items})


# ---------- Chọn đủ video cho 1 tuần / 2 tuần / 1 tháng ----------
@app.get("/api/capacity")
def api_capacity():
    """Số video cần để đăng đủ `days` ngày theo quy tắc của Page (số khung giờ mỗi ngày, ngày nghỉ).
    Chỉ để biết cần tích chọn bao nhiêu video: không phụ thuộc giờ bắt đầu hay kiểu hẹn giờ."""
    page = pages.get(request.args.get("page_id", ""))
    if page is None:
        return err("Chưa chọn Fanpage.")
    try:
        days = int(request.args.get("days", 7))
        if not 1 <= days <= 28:
            raise ValueError
    except ValueError:
        return err("Số ngày phải từ 1 đến 28.")
    rules = planner.rules_of(page)
    if not rules["slots"]:
        return err("Page này chưa có khung giờ đăng nên chưa biết mỗi ngày đăng mấy bài. Vào tab Cài đặt Page > Quy tắc đăng để thêm khung giờ.")
    per_day = planner.posts_per_day(rules)
    cap = pages.effective(page)["publish_limit_24h"]
    cap_left = max(0, cap - len(scheduler.recent_created(page["id"]))) if cap else None
    return jsonify({
        "needed": planner.videos_needed(rules, days),
        "days": days,
        "per_day": per_day,
        "slots": rules["slots"],
        "days_off": rules["days_off"],
        "cap": cap,
        "cap_remaining": cap_left,
    })


# ---------- Tải video ----------
@app.post("/api/download")
def api_download():
    d = body()
    if not d.get("confirm"):
        return err("Cần xác nhận đã được chủ kênh đồng ý trước khi tải.")
    try:
        url = "\n".join(downloader.parse_urls(d.get("url", "")))   # nhiều link: mỗi dòng một link
    except ValueError as e:
        return err(str(e))
    kind = d.get("kind") if d.get("kind") in ("shorts", "videos") else "shorts"
    try:
        limit = max(0, int(d.get("limit", 5)))
    except (TypeError, ValueError):
        return err("Số video không hợp lệ.")
    folder = (d.get("folder") or "").strip()
    note = (d.get("note") or "").strip()[:500]
    fmt = "audio" if d.get("format") == "audio" else "video"
    content = d.get("content") if d.get("content") in downloader.CONTENT_CHOICES else "all"   # Rednote: all | video | images
    page_id = str(d.get("page_id") or "")   # trống = tải không gắn Fanpage, lưu vào thư mục chưa thuộc Page nào
    page = pages.get(page_id) if page_id else None
    if page_id and page is None:
        return err("Không tìm thấy Fanpage này. Chọn lại Fanpage rồi tải video.")
    if manager.has_running("download"):
        return err("Đang có một tác vụ tải chạy. Đợi nó xong hoặc dừng lại.")
    job = manager.start("download", f"Tải {'MP3' if fmt == 'audio' else 'video'} {('cho ' + pages.label(page)) if page else '(không gắn Fanpage)'}: {url.splitlines()[0]}" + (f" (+{len(url.splitlines()) - 1} link)" if "\n" in url else ""), downloader.run, url, folder, kind, limit, note, page_id, fmt, content, page_id=page_id)
    return jsonify({"job": job.id})


# ---------- Hẹn giờ đăng ----------
@app.post("/api/schedule")
def api_schedule():
    d = body()
    dry_run = bool(d.get("dry_run"))
    if not dry_run and not d.get("confirm"):
        return err("Cần xác nhận bạn có quyền đăng các video này lên Fanpage.")
    rels = d.get("rels") or []
    if not rels:
        return err("Chưa chọn video nào.")
    if not isinstance(rels, list) or not all(isinstance(r, str) for r in rels):
        return err("Danh sách video không hợp lệ.")
    page_id = str(d.get("page_id") or "")
    page = pages.get(page_id)
    if page is None:
        return err("Chưa chọn Fanpage. Vào mục Kết nối Fanpage để thêm Page.")
    try:
        datetime.strptime(d.get("start", ""), "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return err("Giờ bắt đầu không hợp lệ.")
    mode = "auto" if d.get("mode") == "auto" else "interval"
    interval = 6.0
    if mode == "interval":   # kiểu tự xếp không dùng khoảng cách giờ
        try:
            interval = float(d.get("interval_hours", 6))
            if not 0 < interval < 24 * 30:
                raise ValueError
        except (TypeError, ValueError):
            return err("Khoảng cách giờ không hợp lệ.")
    tz = pages.effective(page)["tz"]   # múi giờ của Page (đổi ở Cài đặt Page)
    foreign = []
    for r in dict.fromkeys(rels):
        try:
            if library.owner_of_video(r) != page_id:
                foreign.append(r)
        except ValueError as e:
            return err(str(e), 404)
    if foreign:
        return err(f"{len(foreign)} video không thuộc Fanpage này (mỗi thư mục chỉ thuộc một Page). Tải lại trang Thư viện rồi chọn lại.")
    order = d.get("order") if d.get("order") in ("oldest", "newest", "random", "selected", "episode") else "oldest"
    if mode == "auto" and not planner.rules_of(page)["slots"]:
        return err("Page này chưa có khung giờ đăng. Vào tab Cài đặt Page > Quy tắc đăng để thêm, hoặc chọn kiểu hẹn cách nhau cố định.")
    blocked = pages.blocked_until(page)
    if blocked and not dry_run:
        return err(
            f"Facebook đang giới hạn tần suất đăng của Page này, dự kiến đến {blocked.astimezone():%H:%M %d/%m}. "
            "Hãy đợi rồi hẹn tiếp để tránh bị chặn lâu hơn, hoặc bấm \"Bỏ cảnh báo\" ở tab Cài đặt Page nếu chắc chắn đã hết bị chặn."
        )
    why = "" if dry_run else fbgate.why_not(fbgate.COSTS["schedule"])
    if why:
        return err("Chưa hẹn gì. " + why, 429)
    if manager.has_running("schedule") and not dry_run:   # hẹn giờ chạy lần lượt từng việc để không dồn dập lên Facebook
        return err("Đang có một tác vụ hẹn giờ chạy. Đợi nó xong hoặc dừng lại.")
    if manager.has_running("cancel") and not dry_run:
        return err("Đang huỷ lịch nhiều bài. Đợi nó xong rồi hẹn giờ.")
    title = f"{'Xem trước' if dry_run else 'Hẹn giờ'}: {len(rels)} video, {pages.label(page)}"
    job = manager.start("schedule", title, scheduler.run, page_id, rels, d["start"], interval, tz, dry_run, mode, order, bool(d.get("partial")), page_id=page_id)
    return jsonify({"job": job.id})


# ---------- Tác vụ nền ----------
@app.get("/api/jobs")
def api_jobs():
    return jsonify(manager.list())


@app.get("/api/jobs/<job_id>")
def api_job(job_id):
    job = manager.get(job_id)
    if not job:
        return err("Không tìm thấy tác vụ.", 404)
    try:
        since = max(0, int(request.args.get("since", 0) or 0))
    except ValueError:
        since = 0
    return jsonify(job.snapshot(since))


@app.post("/api/jobs/<job_id>/cancel")
def api_cancel(job_id):
    job = manager.get(job_id)
    if not job:
        return err("Không tìm thấy tác vụ.", 404)
    job.cancel_event.set()
    return jsonify({"ok": True})


# ---------- Giới hạn lượt gọi Facebook ----------
@app.get("/api/fb/usage")
def api_fb_usage():
    """Mức dùng lượt gọi Facebook trong 60 phút qua, trạng thái tạm dừng và chi phí ước tính cho một video mỗi thao tác."""
    return jsonify(fbgate.gate.status())


@app.post("/api/fb/usage/clear")
def api_fb_usage_clear():
    """Bỏ trạng thái tạm dừng (chỉ nên dùng khi chắc Facebook đã hết giới hạn). Không xoá số lượt đã đếm trong giờ qua."""
    fbgate.gate.clear_cooldown()
    return jsonify({"ok": True, **fbgate.gate.status()})


# ---------- Cài đặt và token ----------
@app.get("/api/settings")
def api_settings():
    return jsonify(config.public_settings())


@app.post("/api/settings")
def api_save_settings():
    d = body().get("values", {})
    if not isinstance(d, dict):
        return err("Dữ liệu cài đặt không hợp lệ.")
    updates = {}
    for key, value in d.items():
        if key not in config.EDITABLE_KEYS:
            continue
        value = str(value).strip()
        if key in config.SECRET_KEYS and not value:
            continue  # để trống = giữ nguyên giá trị đã lưu
        if config.bad_value(value):
            return err(f"Giá trị của {key} có ký tự không hợp lệ (xuống dòng, ký tự điều khiển hoặc dấu \").")
        updates[key] = value
    if updates:
        config.update_env(updates)
    return jsonify({"ok": True, **config.public_settings()})


@app.get("/api/token/check")
def api_token_check():
    return jsonify(tokens.check_user())


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5173"))
    url = f"http://127.0.0.1:{port}"
    if os.environ.get("NO_BROWSER") != "1":
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    manager.enable_persistence(config.ROOT / "logs" / "jobs")   # giữ nhật ký tác vụ sau khi khởi động lại
    commenter.start_worker(manager)
    print(f"Mở {url} trong trình duyệt. Nhấn Ctrl+C để thoát.")
    app.run(host="127.0.0.1", port=port, threaded=True)
