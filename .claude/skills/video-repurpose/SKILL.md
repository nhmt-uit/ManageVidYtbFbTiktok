---
name: video-repurpose
description: Edit lại video/ảnh để đăng TikTok, Shopee, IG Reels, FB Reels, YouTube Shorts (hook 3s, sub Việt, che sub gốc, âm thanh, khổ dọc 9:16). Dùng khi Tu nhờ edit, dịch sub, dựng lại video, làm slideshow từ ảnh hoặc xử lý cả thư mục cha.
---

# Video repurpose (Tu)

Mục tiêu: từ video hoặc ảnh (thường là thư mục cha có nhiều thư mục con, kèm title/description/hashtags), tạo bản edit để đăng TikTok, Shopee Video, Instagram Reels, Facebook Reels, YouTube Shorts. Claude làm phần cần "nghĩ" (hook, dịch, sub, đề xuất), ffmpeg làm phần xử lý. Luôn có bước Tu duyệt trước khi coi là xong.

## Ưu tiên dùng ManageVideosTool
Phần lớn việc đã có sẵn trong tool (thư mục này, mở ở tab **Chỉnh sửa video** hoặc trong một Fanpage). Đọc `core/editor.py` và README mục "Chỉnh sửa video" trước khi tự viết lệnh ffmpeg mới. Tool đã có:
- Phiên âm sub, dịch tự động qua `claude -p` (provider `claude-code`, không cần khoá API) sang Việt/Anh/Nhật/Trung, sửa tay từng câu, copy toàn bộ có đánh số.
- Giọng đọc riêng thay/trộn với tiếng gốc.
- Che sub gốc in cứng (`core/origsubs.py`): dò vùng và khoảng có sub, che bằng blur + tối, đặt sub mới "Đúng chỗ sub gốc".
- Cắt viền đen có sẵn trong video rồi phóng to cho đầy khung 9:16 (`core/bars.py`).
- Phân tích âm thanh và làm sạch (`core/audioscan.py`; mức Tắt/Nhẹ/Rõ giọng), chuẩn hoá loudnorm, chất lượng xuất Nhẹ/Chuẩn/Cao.
- Hook 3 giây đầu: Claude đề xuất, Tu chọn/sửa, xuất chữ vàng lớn ở 3 giây đầu (`core/hooks.py`).
- Cảnh báo video dài quá 90 giây (không tự cắt).
- Bản nháp `video.draft.mp4`; chỉ khi Tu bấm Duyệt mới thay `video.mp4` gốc.

Chưa có trong tool (làm trực tiếp bằng ffmpeg theo chuẩn bên dưới, hoặc thêm vào tool nếu Tu yêu cầu): chọn thư mục cha và batch, slideshow từ ảnh, preset riêng từng nền tảng, gợi ý xử lý video dài.

## Quy tắc chung
- Không ghi đè hay xoá file gốc. Ghi kết quả cạnh file gốc với hậu tố rõ ràng (`video_vi_sub.mp4`, `video_vi_sub.srt`, `video_clean_for_capcut.mp4`...). Chỉ thay file gốc khi Tu đã duyệt và nói rõ.
- Trả lời tiếng Việt, ngắn gọn. Báo chỗ chưa chắc (dịch, đoạn cắt giữa câu, tên riêng).
- Nhắc Tu một câu về nguồn và quyền sử dụng khi chưa rõ (ví dụ video Rednote): Facebook/TikTok giảm hiển thị nội dung bị coi là không gốc.
- Thông số từng nền tảng đổi theo thời gian: kiểm tra bằng web search trước khi chốt, không dựa vào trí nhớ. Tương tự câu/kiểu trend: tìm lại mỗi lần; nhạc trend không gắn tự động, chỉ gợi ý.

## Quy trình ngoài tool
1. Quét thư mục cha, liệt kê từng thư mục con: loại (video/ảnh), độ dài, độ phân giải, có sub in cứng không, có audio không. Báo bảng tóm tắt.
2. Video dài quá 90 giây: không tự cắt. Đưa 3 hướng: chia phần (Phần 1/2), bản rút gọn highlight, hoặc giữ nguyên cho YouTube.
3. Đề xuất cho Tu duyệt: hook 3 giây (khoảnh khắc mạnh nhất, chữ lớn, zoom nhẹ), sub/bản dịch, đoạn cắt, caption, hashtag, câu trend.
4. Sau khi Tu duyệt: render từng nền tảng, kiểm tra (xem khung hình mẫu, dấu tiếng Việt, độ dài, âm lượng), nói rõ file nằm ở đâu.

## Thư mục chỉ có ảnh
Ghép thành video 1080x1920, chuyển động nhẹ (zoom/pan chậm), mỗi ảnh khoảng 2–3 giây, tổng dưới 90 giây. Tự nghĩ: hook 3 giây đầu, sub theo từng ảnh, caption, gợi ý nhạc nền. Gửi đề xuất cho Tu duyệt trước khi render.

## Chuẩn kỹ thuật (ffmpeg)
- 9:16, 1080x1920, scale lanczos, unsharp nhẹ; H.264 yuv420p, crf 18–20, preset veryfast, AAC 192k, +faststart. Lên 1080p từ 720p chỉ là scale thường (không phải AI upscale; Real-ESRGAN chỉ khi Tu yêu cầu vì nặng).
- Âm thanh: highpass nhẹ, afftdn, loudnorm khoảng I=-14 đến -16 LUFS, TP=-1.5; giọng rõ hơn nhạc nền. Chỉ tăng cường khi số đo (SNR, tiếng nền) cho thấy cần.
- Sub đặt trên vùng UI của nền tảng (tránh khoảng 20% dưới cùng và cạnh phải).
- Cắt viền đen trước khi scale; che sub gốc trước khi cắt (toạ độ gốc). Che sub mà sub mới không đặt "Đúng chỗ sub gốc" thì sub lệch khỏi vùng che.

## CapCut
Mặc định: đưa video nền + file SRT để Tu import (Captions, Local captions). Ghi thẳng project (`~/Movies/CapCut/User Data/Projects/com.lveditor.draft/<tên>/`) chỉ khi Tu đồng ý và đã đóng CapCut; sao lưu `root_meta_info.json` trước, chỉ thêm project mới, nói rõ là chưa kiểm tra được project có mở đúng không.

## Ghi chú môi trường
- Test trong container của Claude: không gọi được Facebook/YouTube/Rednote và `claude -p` thật; dùng bản giả. Đường dẫn có tiếng Trung/emoji phải truyền đúng nguyên văn.
- Muốn xem khung hình thì chép sang container (`device_stage_files`), xử lý bằng ffmpeg, rồi chép kết quả về cạnh file gốc.
- Model whisper (ggml) không tải được từ container (huggingface bị chặn); nhờ Tu tải về thư mục đã cấp quyền. Với video đã có sub in cứng thì dùng cách dò sub của `origsubs.py`.
