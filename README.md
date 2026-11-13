# Quản lý video

Ứng dụng web chạy trên máy bạn (http://127.0.0.1:5173), quản lý nhiều Fanpage theo kiểu mỗi Page là một không gian làm việc riêng, giống Meta Business Suite.

**Mở app là vào trang Tổng quan**: mỗi Fanpage là một thẻ cho biết hôm nay đã hẹn mấy bài (so với số bài mỗi ngày của Page), bao nhiêu video chờ đăng, chưa lên lịch, đã đăng, lỗi, đã hẹn bao nhiêu trong 24 giờ qua, bài kế tiếp, **kho video còn đủ đăng mấy ngày** (chuyển đỏ khi sắp hết) và trạng thái bị Facebook giới hạn. Bấm **Mở Page** để vào làm việc với Page đó. Trong Page, thanh phía trên có **← Tổng quan** để quay về và ô **Đang làm việc với Fanpage** để chuyển sang Page khác. Mọi thứ bên dưới chỉ thuộc về Page đang chọn:

1. **Tải video** từ kênh YouTube, TikTok hoặc Rednote đã đồng ý cho bạn dùng, lưu vào thư mục đặt tên (thư mục đó thuộc Page đang chọn), kèm tiêu đề, mô tả, hashtag.
2. **Thư viện & Lên lịch**: xem, sửa nội dung, chọn video rồi hẹn giờ đăng Reels lên Fanpage Facebook. Chỉ thấy video của các thư mục thuộc Page này. Có theo dõi video đã đăng thật chưa, hẹn lại video lỗi và nhập link affiliate riêng cho từng video bằng CSV.
3. **Lịch**: xem theo tuần các video đã hẹn giờ của Page, ngày nghỉ được tô xám, giờ theo múi giờ của Page. Bài chưa đăng có thể huỷ hoặc đổi giờ (xem mục bên dưới).
4. **Thống kê**: đã đăng bao nhiêu bài, tỷ lệ đăng thành công, lịch sắp tới, kho video và số bài hẹn thêm được ngay (xem mục "Thống kê bài đăng").
5. **Cài đặt Page**: đổi tên, bật/tắt tự động comment, quy tắc đăng (khung giờ, ngày nghỉ, số bài tối đa mỗi ngày), múi giờ riêng (mặc định Việt Nam, Asia/Ho_Chi_Minh), giới hạn 24 giờ, nghỉ giữa các video, thời gian chờ và nghỉ giữa các comment, kho comment, kiểm tra token.
6. **Nhật ký**: các tác vụ của Page đang chọn.

Ở màn hình chung (Tổng quan) còn có:
- **Kết nối Fanpage**: thêm Page từ Facebook, kiểm tra token, mở Page, xóa khỏi app.
- **Cài đặt chung**: **Mặc định Page** (giá trị dùng cho Page nào chưa đặt riêng: giới hạn 24 giờ, nghỉ giữa video, thời gian chờ và nghỉ giữa comment), **Token FB** (App ID, App Secret, User token lưu trong `.env`, nút kiểm tra), **Thông báo** (macOS và Telegram, xem mục "Thông báo sự cố") và **Chung** (thư mục lưu video, chất lượng tải, khoảng cách giờ mặc định...).
- **Nhật ký** của mọi Page.

Chỉ dùng với video của bạn, hoặc video có sự đồng ý của chủ kênh. Mỗi lần tải, app yêu cầu xác nhận và lưu ghi chú đồng ý vào `permission.json` trong thư mục kênh.

## Chạy

```bash
cd ManageVideosTool
brew install ffmpeg deno     # lần đầu: ffmpeg (kèm ffprobe) để ghép video và kiểm tra Reels, deno để yt-dlp lấy đủ định dạng
./run.sh
```

`run.sh` tự tạo môi trường ảo `.venv`, cài thư viện và mở trình duyệt. Nếu báo không có quyền chạy: `chmod +x run.sh`.

### Chạy nền, không cần mở terminal (macOS)

Muốn thông báo Telegram, tự động comment và cảnh báo kho video hoạt động mà không phải giữ terminal, bật chế độ chạy nền bằng `launchd`:

```bash
chmod +x service.sh      # chỉ lần đầu
./service.sh on          # bật: app chạy nền, tự chạy mỗi khi đăng nhập máy, tự bật lại nếu bị sập
```

Sau khi bật, đóng terminal thoải mái và mở http://127.0.0.1:5173 bằng trình duyệt (nên lưu bookmark; chế độ nền không tự mở trình duyệt).

| Lệnh | Việc làm |
|---|---|
| `./service.sh on` | Bật và chạy ngay |
| `./service.sh on --awake` | Bật, kèm giữ máy không tự ngủ khi rảnh (`caffeinate`). Gập màn hình laptop vẫn làm máy ngủ |
| `./service.sh off` | Tắt và gỡ hẳn, máy không còn tự chạy app |
| `./service.sh restart` | Chạy lại, dùng sau khi cập nhật code |
| `./service.sh status` | Xem đang chạy hay không |
| `./service.sh logs` / `logs -f` | Xem nhật ký (`logs/server.log`, tự chuyển sang `.1` khi quá 5 MB) |

Lưu ý:
- Máy ngủ hoặc tắt thì app dừng; comment bị lỡ sẽ được bù khi app chạy lại (trong vòng 3 ngày).
- Không chạy `./run.sh` khi chế độ nền đang bật vì hai bên dùng chung cổng 5173. Muốn chạy tay thì `./service.sh off` trước.
- Script chỉ ghi file `~/Library/LaunchAgents/com.managevideos.app.plist` của riêng bạn, không cần quyền admin. Nếu bật lỗi, `./service.sh off` luôn gỡ sạch.
- Thay đổi cài đặt trong giao diện có hiệu lực ngay; chỉ cần `restart` khi cập nhật code. Riêng việc tự cập nhật yt-dlp, app tự khởi động lại giúp bạn (xem mục Cập nhật yt-dlp).

## Dùng lần đầu

Nếu bạn đã dùng bản một Page: Page cũ, token, kho comment và công tắc tự động comment tự chuyển sang `pages.json` ở lần chạy đầu, các video đã hẹn giờ vẫn thuộc về Page đó.

1. **Cài đặt > Token FB**: điền App ID, App Secret, User token (lấy ở Graph API Explorer, nhớ chọn tất cả Fanpage muốn quản lý), bấm **Lưu**.
2. **Kết nối Fanpage**: bấm **Lấy danh sách từ Facebook**, tick các Page muốn dùng rồi **Thêm**. Bấm **Kiểm tra token** ở từng Page để xem hạn dùng và quyền còn thiếu (cần `pages_manage_posts` và `publish_video`).
3. Mở Page rồi vào tab **Tải video**: dán link kênh (ví dụ `https://www.youtube.com/@tenkenh`), đặt tên thư mục, chọn Shorts hoặc Video thường, tích xác nhận, bấm **Tải về**.
   - Ô **Số video mới cần tải** chỉ đếm video MỚI: video đã có trong các thư mục của Page được bỏ qua và không tính vào số này. Ví dụ đã có 100 video, nhập 100 thì app tải thêm 100 video mới (nhập 0 = tải tất cả video mới). Video lỗi không tính vào số này, nhưng 10 video liên tiếp lỗi thì app dừng (YouTube có thể đang chặn).
   - Ô **Tải về** cho chọn **Chỉ âm thanh (MP3 320 kbps)**: mỗi video lưu thành `audio.mp3` trong thư mục con của video. Nếu video đó đã được tải rồi (kể cả khi tiêu đề trên YouTube đã đổi), MP3 vào đúng thư mục của video, không ghi đè tiêu đề hay mô tả. MP3 chống trùng riêng theo file `audio.mp3` trong các thư mục của Page. Thư mục chỉ có MP3 không hiện ở Thư viện và không dùng để hẹn đăng. Video có kèm MP3 hiện nhãn "Có MP3". Cần ffmpeg (đã cần sẵn để ghép video). Tải xong mà không thấy file (ví dụ thiếu ffmpeg) thì tính là lỗi và app dọn thư mục vừa tạo.
4. Tab **Thư viện & Lên lịch**: tích chọn video rồi bấm **Lên lịch...** (nút ở thanh trên hoặc ở thanh nổi phía dưới). Cửa sổ **Lên lịch đăng lên Fanpage** hiện ra, Fanpage và múi giờ lấy theo Page đang làm việc (muốn đổi Page, đóng cửa sổ rồi chuyển Page ở thanh phía trên): chọn kiểu hẹn giờ (cách nhau cố định hoặc tự xếp theo khung giờ của Page), bấm **Xem trước kế hoạch** rồi **Lên lịch đăng**. Cửa sổ này đóng được bất cứ lúc nào (nút Đóng, phím Esc hoặc bấm ra ngoài); tác vụ đang chạy vẫn tiếp tục. Nên thử với 1 video trước. Facebook chỉ cho hẹn giờ trong khoảng từ 10 phút đến 29 ngày kể từ bây giờ; app kiểm tra trước và báo nếu video cuối cùng vượt giới hạn này.

## Thư mục video và nơi đăng

Mục **Thư mục** (thanh trên cùng) liệt kê mọi thư mục video, kể cả thư mục trống, với số video chưa hẹn / chờ đăng / đã đăng.

- **Nơi đăng:** mỗi thư mục chọn nơi đăng cho từng nền tảng, mỗi nền tảng tối đa một tài khoản. Hiện có Facebook (một Page). Instagram, TikTok, YouTube sẽ thêm sau. Một Page có thể có nhiều thư mục, hoặc không có thư mục nào. Lưu trong `channel.json` của thư mục: `{"targets": {"facebook": "<page_id>"}, "page_id": "...", "auto_delete": {...}}` (giữ `page_id` để bản cũ vẫn đọc được; file cũ chỉ có `page_id` được hiểu là Facebook).
- **Gán / đổi / bỏ gán:** chọn Page trong ô Facebook của thư mục (chọn "Không đăng Facebook" để bỏ gán). Video đã đăng giữ nguyên lịch sử. Nếu thư mục còn video **chờ đăng** (kể cả bài lỗi / quá giờ) trên Page cũ, app hỏi có huỷ lịch các video đó (xóa bài hẹn trên Facebook) rồi đổi không; huỷ chưa hết thì không đổi. Không đổi được khi đang tải video, hẹn lịch hoặc huỷ lịch.
- **Tạo thư mục mới** (có thể chọn Page luôn). **Tự xoá sau khi đăng** cài ở từng thư mục (xem phần Xoá video).
- Thư mục tải về từ một Page tự thuộc Page đó. Tải cho Page khác vào thư mục đang thuộc Page này sẽ bị từ chối. Thư mục không có Page Facebook thì không hiện trong Thư viện của Page nào (Tổng quan và Thư viện có nhắc).
- Nâng cấp từ bản cũ: thư mục chưa ghi Page mà mọi video đã hẹn đều của cùng một Page thì tự gán cho Page đó. Thư mục bạn đã bỏ gán (hoặc tạo mới không chọn Page) thì không bao giờ bị tự gán lại. Xóa một Page khỏi app thì thư mục của nó hiện "(Page đã bị xoá khỏi app)" để chọn lại.
- Video nằm thẳng ở thư mục gốc (tải bằng script cũ) không có thư mục kênh nên chỉ hiện ở Page đã hẹn nó.

## Múi giờ và cài đặt riêng từng Page

Mỗi Page có múi giờ riêng (mặc định Asia/Ho_Chi_Minh). Khung giờ đăng, giờ mặc định trong khung Lên lịch, giờ hiển thị trên thẻ video và Lịch đều tính theo múi giờ của Page. Giới hạn 24 giờ, nghỉ giữa hai video, thời gian chờ và nghỉ giữa các comment có thể đặt riêng cho Page (ô để trống = dùng mặc định ở Cài đặt chung > Mặc định Page).

## Lên lịch thông minh

Mỗi Fanpage có **Quy tắc đăng** (tab Cài đặt Page): các khung giờ trong ngày (ví dụ `12:00, 19:00, 21:00`), ngày nghỉ và số bài tối đa mỗi ngày. Trong cửa sổ **Lên lịch đăng** có hai kiểu hẹn giờ:

- **Cách nhau cố định**: giờ đầu tiên + khoảng cách giờ như trước.
- **Tự xếp vào khung giờ của Page**: app lần lượt điền video vào các khung giờ còn trống từ thời điểm bạn chọn (mặc định là ngay bây giờ). Nó bỏ qua ngày nghỉ, khung giờ đã có bài của Page đó (kể cả bài đã hẹn từ trước), giờ chưa cách hiện tại đủ xa và quá 29 ngày. Không đủ chỗ thì báo rõ xếp được bao nhiêu video, không hẹn gì cả. Khung giờ tính theo múi giờ của Page.

**Chọn đủ video cho 1 tuần, 2 tuần hoặc 1 tháng**: ở Thư viện bấm **Chọn đủ cho...** rồi chọn 1 tuần, 2 tuần hoặc 1 tháng. App tính theo Fanpage đang làm việc. App chỉ tích chọn một số lượng video, chưa xếp lịch gì cả:
- Số video = số ngày đăng × số bài mỗi ngày của Page (số khung giờ, không vượt "tối đa mỗi ngày"), trừ các ngày nghỉ trong tuần. Ví dụ khung giờ 12:00, 14:00, 16:00 và tối đa 3 bài/ngày thì 1 tuần (7 ngày, không có ngày nghỉ) = 21 video.
- Số này không phụ thuộc ngày bắt đầu, kiểu hẹn giờ hay các bài đã hẹn sẵn. Chọn xong, bấm **Lên lịch...** rồi đăng theo "Tự xếp" hoặc "Cách nhau cố định", bắt đầu từ ngày nào cũng được. Với "Cách nhau cố định" bạn có thể đăng né các khung giờ/ngày đã đầy (app chỉ cảnh báo, không chặn); "Tự xếp" tự bỏ qua ngày và khung giờ đã đầy.
- Chọn theo "Thứ tự đăng" đang chọn, chỉ trong các video chưa lên lịch đang hiển thị. Không đủ video thì chọn hết và báo còn thiếu bao nhiêu. Page chưa có khung giờ thì báo cần thêm khung giờ ở tab Cài đặt Page.
- "1 tháng" tính là 28 ngày vì Facebook chỉ cho hẹn giờ trong 29 ngày. Nếu số video vượt giới hạn mỗi 24 giờ (mục bên dưới), app báo rõ mỗi đợt chỉ hẹn được bao nhiêu video, phần còn lại hẹn tiếp sau.

**Thứ tự đăng** có bốn lựa chọn: video cũ trước (mặc định), mới trước, ngẫu nhiên, hoặc theo thứ tự bạn tích chọn.

**Cảnh báo spam** hiện sau khi bấm **Xem trước kế hoạch** (và trong nhật ký khi đăng thật), không chặn bạn: một ngày vượt số bài tối đa của Page, hai bài cách nhau dưới 60 phút, hoặc bật tự động comment với từ 5 bài trở lên mà kho comment chỉ có dưới 3 câu.

Giới hạn: app không đổi giờ của video đã hẹn trên Facebook; tab **Lịch** chỉ để xem. Video báo lỗi thì bấm **Hẹn lại** ở Thư viện.

## Huỷ lịch và đổi giờ bài đã hẹn

Bài đã hẹn mà chưa đăng có hai nút ở tab Lịch và ở thẻ video trong Thư viện:

- **Huỷ lịch:** app xóa bài hẹn trên Facebook, rồi gỡ lịch trong app (bản cũ giữ ở `scheduled.old.json`). Video quay về "Chưa lên lịch". Nếu Facebook từ chối xóa hoặc đang giới hạn lượt gọi, app không đổi gì để hai bên không lệch: bài vẫn nằm trong app và VẪN còn trên Facebook, sẽ được đăng đúng giờ. Khi đó hãy huỷ bài trong Meta Business Suite (Nội dung đã lên lịch), bấm **Kiểm tra trạng thái** rồi **Hẹn lại**. Với từng bài, app còn hỏi "chỉ gỡ lịch trong app" nhưng chỉ làm khi Facebook xác nhận bài không còn hẹn giờ; còn thì từ chối.
- **Facebook báo "Object ... does not exist" khi xóa:** câu này Facebook dùng cho cả bài đã mất, cả lúc nó đang lỗi hoặc token thiếu quyền, nên app không tin ngay. Chỉ khi đọc lại bài hai lần (cách nhau vài giây) Facebook đều không thấy, và token vẫn đọc được chính Page, app mới coi là đã mất và gỡ lịch (câu gốc Facebook trả được ghi vào nhật ký đợt huỷ và vào `cancel_detail` trong `scheduled.old.json`). Nếu 3 bài liên tiếp đều báo "không còn", app dừng cả đợt: bài xóa thật hiếm khi dồn thành chuỗi, thường là Facebook đang lỗi, mà bài còn thì vẫn được đăng. Hãy mở Meta Business Suite kiểm tra; bài chưa xử lý vẫn giữ nguyên trong app.
- **Đổi giờ:** app thử sửa giờ hẹn trực tiếp trên Facebook. Nếu Facebook không cho, app hỏi bạn có muốn huỷ bài cũ rồi tải lại video và hẹn lại vào giờ mới không (tốn thêm một lượt vào giới hạn đăng 24 giờ). Giờ mới tính theo múi giờ của Page, phải cách hiện tại ít nhất 15 phút và trong vòng 29 ngày.
- Bài đã đăng (hoặc vừa đăng) không huỷ hay đổi giờ được. Bài báo lỗi dùng nút "Hẹn lại" như trước.
- Bài đã huỷ vẫn được tính vào giới hạn 24 giờ của Page, vì lần hẹn trước đó đã gọi API Facebook.

### Ba nút công cụ của Thư viện

| Nút | Làm gì | Có gọi Facebook không | Hiện ở tab |
| --- | --- | --- | --- |
| **Kiểm tra Reels** | soát file các video chưa lên lịch (dọc 9:16, 3 đến 90 giây, tối thiểu 540x960, có tiếng) bằng ffprobe | không | Tất cả, Chưa lên lịch |
| **Kiểm tra trạng thái** | hỏi Facebook lần lượt từng bài đã hẹn (bỏ qua bài đã đăng): đã đăng, lỗi hay đã bị xóa | có (chỉ đọc) | Tất cả, Chờ đăng, Lỗi / quá giờ |
| **Làm mới** | đọc lại danh sách từ thư mục video trên máy (video mới tải, file bạn vừa sửa) | không | mọi tab |

Tab Đã đăng không có nút kiểm tra nào vì bài đã đăng xong. Dưới các nút có một dòng giải thích việc có thể làm ở tab đang xem.

### Chọn nhiều video và thao tác hàng loạt

Mỗi tab trong Thư viện có trạng thái khác nhau nên ô chọn và các nút chọn nhanh hoạt động theo tab:

| Tab | Ô chọn ở thẻ video | **Chọn tất cả** | **Chọn đủ cho...** | Nút hiện ra khi có video được chọn |
| --- | --- | --- | --- | --- |
| Tất cả | video chưa lên lịch | tất cả video chưa lên lịch đang hiện | dùng được | **Lên lịch...** |
| Chưa lên lịch | video chưa lên lịch | tất cả video đang hiện | dùng được | **Lên lịch...** |
| Chờ đăng | bài đã hẹn, chưa đăng | tất cả bài chờ đăng đang hiện | tắt (không có gì để lên lịch) | **Huỷ lịch** |
| Lỗi / quá giờ | bài báo lỗi, bài quá giờ mà chưa đăng, video bị thiếu trên Facebook | tất cả bài đang hiện | tắt | **Huỷ lịch** (bài quá giờ) và **Hẹn lại** (bài lỗi hoặc thiếu) |
| Đã đăng | không có | tắt | tắt | không có |

- **Huỷ lịch hàng loạt:** hỏi xác nhận, rồi chạy nền như một tác vụ (xem tiến độ ở tab Nhật ký, chuyển tab vẫn chạy tiếp). App xóa từng bài trên Facebook với nhịp chậm. Hộp xác nhận báo trước còn bao nhiêu lượt gọi Facebook trong giờ này (mỗi bài tốn khoảng 1 lượt, xem mục **Giới hạn lượt gọi API của cả app**). Hết lượt, hoặc Facebook báo **giới hạn lượt gọi API** (code 4, 17, 613...), thì app **dừng ngay**, không gọi thêm: các bài chưa huỷ giữ nguyên trong Chờ đăng (chúng vẫn còn trên Facebook, sẽ được đăng đúng giờ); đợi theo số phút app báo rồi chọn lại và huỷ tiếp. Gặp 3 lần liên tiếp lỗi kết nối thì cũng dừng. Bài Facebook từ chối xóa vẫn giữ lịch trong app và app hiện cảnh báo rõ là bài vẫn còn trên Facebook, kèm cách xử lý. Bài báo "không còn" chỉ được tính là đã xóa khi đọc lại Facebook cũng không thấy bài. Mỗi lần tối đa 300 bài.
- **Hẹn lại hàng loạt:** đưa các bài lỗi hoặc thiếu về "Chưa lên lịch" để lên lịch lại. Không gọi Facebook.
- Khi đang huỷ lịch hàng loạt, app không cho bắt đầu lên lịch mới để hai việc không dẫm lên nhau.
- Đổi tab hoặc đổi kênh thì những video đã chọn nhưng không còn hiện sẽ tự bỏ chọn, nên không có chuyện huỷ nhầm bài đang ẩn. Cửa sổ **Lên lịch** chỉ nhận các video chưa lên lịch trong số đã chọn.

## Thống kê bài đăng

Tab **Thống kê** của từng Page giúp cân nhắc trước khi hẹn thêm nhiều bài. App chỉ đọc dữ liệu có sẵn (`scheduled.json`, `scheduled.old.json`), **không gọi Facebook** nên không tốn lượt gọi. Bấm **Làm mới** để tính lại.

- **Các ô đầu trang:** số bài đã đăng (kèm 7 ngày và 30 ngày qua), tỷ lệ đăng thành công, chờ đăng, chưa lên lịch, lỗi hoặc quá giờ.
- **Tỷ lệ đăng thành công** = bài đã đăng / (bài đã đăng + lỗi + không thấy trên Facebook + bài đã tới giờ mà chưa xác nhận). Trạng thái lấy từ lần Kiểm tra trạng thái gần nhất, nên bài đã tới giờ mà chưa kiểm tra được tách riêng thành "chưa xác nhận" thay vì đoán. Muốn số chính xác thì bấm Kiểm tra trạng thái ở Thư viện trước.
- **Trước khi hẹn thêm:** Page còn đủ bài cho bao nhiêu ngày (lịch đã hẹn cộng kho video), và **hiện hẹn được thêm tối đa bao nhiêu video** = số nhỏ hơn giữa phần còn lại của giới hạn 24 giờ của Page và số lượt gọi Facebook còn trong giờ chia cho 3 lượt mỗi video. Kèm cảnh báo nếu còn bài lỗi hoặc chưa xác nhận.
- **Hai biểu đồ 14 ngày:** đã đăng (so với số bài mục tiêu mỗi ngày theo quy tắc của Page, ngày đã qua mà thiếu bài tô vàng) và sắp đăng (ngày trống là chỗ còn nhận thêm bài).
- **Comment affiliate** (đã comment bao nhiêu bài đã đăng, đang chờ, lỗi, quá hạn), **bài đã huỷ hoặc gỡ lịch trong 30 ngày qua** theo lý do, bảng theo từng thư mục kênh, và 10 bài đã đăng gần nhất.
- **Chưa có** lượt xem, like hay lượt tiếp cận: các số đó phải lấy từ Insights của Facebook, cần thêm quyền và tốn lượt gọi.

## Chỉnh sửa video (phụ đề, giọng đọc, khung 9:16)

**Mở ở đâu:** mục **Chỉnh sửa video** trên thanh trên cùng (cạnh Tải video) liệt kê mọi video trong thư mục video, không cần chọn Fanpage; lọc theo tình trạng (chưa chỉnh sửa, chờ duyệt, đã chỉnh sửa), theo thư mục kênh hoặc tìm theo tên. Trong một Fanpage, thẻ video ở Thư viện vẫn có nút **Chỉnh sửa video** như cũ. Cả hai cùng mở một hộp thoại chỉnh sửa.

Facebook giảm phân phối video đăng lại nguyên bản. Nút **Chỉnh sửa video** trên mỗi thẻ ở Thư viện (chỉ hiện với video chưa lên lịch) giúp thêm giá trị thật vào video trước khi đăng:

1. **Phiên âm tự động** bằng whisper.cpp (chạy trên máy, dùng GPU Metal của Mac Apple Silicon). Chọn ngôn ngữ trong video; nếu đã thêm giọng đọc thì phiên âm từ giọng đó.
2. **Sửa phụ đề**: sửa chữ, chỉnh giây bắt đầu/kết thúc, thêm/xóa dòng, bấm ▶ để nghe lại. Khung xem trước hiện phụ đề đè lên video hiện tại.
3. **Giọng đọc / bình luận của bạn** (tùy chọn): tải file mp3, m4a, wav... lên; giọng được trộn vào, âm gốc nhỏ lại (chỉnh được).
4. **Xuất video**: 1080x1920 (9:16), H.264 + AAC, chuẩn hóa âm lượng. Video ngang được đặt giữa nền mờ (hoặc cắt giữa, hoặc viền đen). Phụ đề in vào hình, có tiếng Việt đủ dấu; chọn vị trí, cỡ chữ, màu, nền mờ.

Xuất xong chỉ ra **bản nháp** `video.draft.mp4`; chưa duyệt thì video thật (`video.mp4`), kiểm tra Reels và hẹn giờ đăng vẫn dùng video hiện tại. Xem thử bản nháp trong hộp thoại rồi chọn: **Bỏ bản nháp** (không đổi gì, phụ đề và giọng đọc vẫn giữ để xuất lại) hoặc **Duyệt & thay video gốc**. **Duyệt là không hoàn tác được**: bản nháp ghi đè `video.mp4`, video gốc bị xoá hẳn, phụ đề/giọng đọc đã dùng được dọn đi, và thẻ có nhãn "Đã chỉnh sửa video" (file `edit_approved.json`). Video đã lên lịch thì không xuất/duyệt được (Facebook đã nhận bản cũ): huỷ lịch, chỉnh, rồi hẹn lại. Mỗi lúc chỉ chạy một tác vụ chỉnh sửa.

**Dịch phụ đề sang tiếng Việt** (video tiếng Anh, Nhật, Hàn, Trung...): phiên âm với đúng ngôn ngữ trong video, rồi dùng một trong hai cách ở bước 2 (mỗi dòng phụ đề có số thứ tự; hộp thoại rộng để xem video và danh sách cùng lúc):
- **Dịch tự động bằng AI**: chọn ngôn ngữ đích ở ô *Dịch sang* (Tiếng Việt, Anh, Nhật, Trung) rồi bấm *Dịch tự động*; dịch lại sang ngôn ngữ khác luôn xuất phát từ câu gốc, không dịch chồng lên bản dịch. Nhà cung cấp chọn ở *Cài đặt chung > Dịch phụ đề*. Mặc định là **Claude Code** (không cần khóa API): app chạy `claude -p` trên máy bạn với đăng nhập Claude Code sẵn có, mỗi lượt 40 dòng, tính vào hạn mức Claude Code của bạn (xem mục Hook về cách cài, `CLAUDE_BIN`, `HOOK_MODEL`). Nếu máy chưa có Claude Code mà bạn đã nhập khóa API thì app vẫn dùng API như trước. Hoặc chọn Anthropic (Claude) qua API, hoặc mọi dịch vụ theo chuẩn OpenAI (OpenAI, Google Gemini, OpenRouter, Groq, Ollama chạy trên máy...). Nhập khóa API, model, địa chỉ API (nếu cần) rồi bấm *Thử dịch*. Cấu hình lưu vào `.env` (`TRANSLATE_PROVIDER`, `TRANSLATE_API_KEY`, `TRANSLATE_MODEL`, `TRANSLATE_BASE_URL`); khóa không bao giờ hiện lại trên giao diện. App chỉ gửi chữ của phụ đề, không gửi video hay âm thanh. Mốc thời gian giữ nguyên; mỗi câu dịch có câu gốc hiện bên dưới để đối chiếu.
- **Dịch tay**: bấm *Sao chép bản gốc* (các câu được đánh số), dịch ở đâu cũng được (ChatGPT, Google Dịch, tự dịch...), rồi bấm *Dán bản dịch…* và dán lại, mỗi câu một dòng đúng thứ tự (có hoặc không có số đầu dòng). Hoặc sửa thẳng từng ô: với video không phải tiếng Việt, câu bạn gõ đè lên được coi là bản dịch và câu gốc được giữ lại.
*Trả về bản gốc* hoàn tác bản dịch. Hình xuất ra chỉ in bản dịch. AI có thể dịch sai tên riêng hay thuật ngữ nên luôn đọc lại.

**Che sub gốc (video đã có sub in cứng, ví dụ video Rednote/Douyin):** trong hộp thoại Chỉnh sửa video, bước **4. Che sub gốc**:
1. Bấm **Dò sub gốc** (vài giây, chạy trên máy). Nếu tìm thấy sub, app tự tick *Che sub gốc khi xuất* và đặt vị trí phụ đề *Đúng chỗ sub gốc* (đổi lại ở bước 6 nếu muốn); phần xem trước trên video cũng làm mờ vùng sub cũ và đặt phụ đề mới chính giữa vùng đó. App tìm chữ trắng viền đen lặp lại ở một dải ngang trong hình, rồi lưu vùng đó và các khoảng thời gian có sub vào `origsubs.json` của video. Khung cam đứt nét trên video xem trước là vùng sẽ được che.
2. Nếu khung lệch, hoặc video có sub nhưng không dò ra, chỉnh 4 số (cách mép trên/trái, cao, rộng, theo % khung hình) rồi bấm **Lưu vùng che**. Ô **Che** chọn *Chỉ lúc có sub* (mặc định) hoặc *Suốt video*.
3. Tick **Che sub gốc khi xuất**. Vùng đó được làm mờ và tối đi trong các khoảng có sub; sub mới do bạn viết/dịch in lên trên. Ở bước 6 nên chọn vị trí phụ đề **Đúng chỗ sub gốc** để sub mới nằm đúng chỗ cũ.
- Việc che được làm trước khi đổi khung 9:16, nên đúng với cả kiểu *Nền mờ*, *Cắt giữa* và *Viền đen*. Che bằng làm mờ chứ không "xoá" được chữ: nền phía sau không thể dựng lại.
- Cần thư viện `numpy` (đã thêm vào `requirements.txt`). Máy đã cài trước đó: `.venv/bin/pip install numpy` rồi `./service.sh restart`.
- Sub nằm sát mép khung hoặc quá mờ/nhỏ có thể không dò ra: dùng nhập tay như bước 2. `origsubs.json` bị xoá khi bạn Duyệt (video mới đã che xong, dữ liệu cũ không còn đúng).

**Cắt viền đen có sẵn (bước 6):** nhiều video tải về (Rednote, Douyin...) đã bị đóng khung đen quanh hình, nên dù app phóng 720x1280 lên 1080x1920 thì viền đen vẫn còn. Ô **Cắt viền đen có sẵn trong video** (mặc định bật) cho app dò viền ở 8 thời điểm trong video rồi cắt bỏ trước khi phóng to, nên hình đầy khung. Chỉ cắt khi viền đủ rõ (từ 1,2% mỗi cạnh trở lên) và vùng giữ lại còn ít nhất 60%; cảnh tối đơn lẻ không bị cắt nhầm vì lấy vùng chung của các thời điểm. Nếu video của bạn có cảnh tối kéo dài cả video mà bị cắt thiếu, bỏ tick ô này. Khung *Tự chọn* với video gần 9:16 giờ phóng cho đầy khung thay vì để lại viền mỏng.

**Làm sạch âm thanh và chất lượng xuất (bước 6):**
- **Làm sạch âm thanh** chỉ áp cho tiếng của video gốc, không đụng giọng đọc bạn thêm vào. *Nhẹ*: cắt tiếng ù thấp và giảm ồn nền. *Rõ giọng nói*: thêm tăng dải giọng (3 kHz) và nén nhẹ cho tiếng đều hơn. Mặc định *Tắt*. Video có nhạc nền thì nên dùng *Nhẹ*, vì giảm ồn mạnh có thể làm nhạc nghe méo.
- **Phân tích âm thanh** (nút ngay dưới ô chọn): ffmpeg và numpy đo mức ồn nền, độ chênh giữa tiếng nói và nền, tiếng ù trầm, tiếng xì dải cao, độ lớn (LUFS) và âm thanh bị vỡ, rồi gợi ý chế độ làm sạch kèm lý do. Bấm **Dùng gợi ý** để điền vào ô chọn. Đây chỉ là số đo và ngưỡng kinh nghiệm (chưa hiệu chỉnh trên nhiều video thật), không phải tai nghe: luôn nghe lại bản nháp trước khi Duyệt. Kết quả lưu ở `audioscan.json` của video và bị xoá khi Duyệt.
- Sau khi xuất có làm sạch (và không trộn giọng đọc), app đo lại 60 giây đầu và ghi độ chênh tiếng nói so với nền trước/sau vào nhật ký tác vụ và `edit.json` (`audio_report`). Video có nhạc nền liên tục thường chỉ cải thiện rất ít.
- **Chất lượng xuất**: *Nhẹ* (CRF 23, âm thanh 128k), *Chuẩn* (CRF 20, 160k, mặc định), *Cao* (CRF 17, 192k, file lớn hơn).
- Video dài hơn 90 giây vẫn xuất được nhưng app ghi cảnh báo trong nhật ký và trong thông báo kết quả.

**Hook 3 giây đầu (bước 5, nhờ Claude đề xuất):** bấm **Nhờ Claude đề xuất hook**, app chạy `claude -p` (Claude Code) trên máy bạn, gửi tên video và phụ đề đã phiên âm, rồi nhận về 5 hook (kèm kiểu và lý do), vài câu trend và câu kêu gọi cuối video.
- Chọn **Dùng** ở một hook (hoặc tự viết), sửa chữ rồi bấm **Duyệt hook**. Chỉ hook đã duyệt mới được in; tick **In hook ở 3 giây đầu khi xuất**. Chữ vàng viền đen hiện ở phần trên của khung hình trong 3 giây đầu và có xem trước trên video.
- Cần Claude Code đã cài và đăng nhập trên máy (chạy `claude` trong Terminal một lần). Nếu lệnh nằm chỗ lạ, đặt `CLAUDE_BIN=/đường/dẫn/claude` trong `.env`; đặt `HOOK_MODEL` nếu muốn chỉ định model. Lệnh chạy trong thư mục tạm và không cho dùng công cụ nào.
- Claude chỉ nhận chữ, không xem được hình hay nghe được tiếng, và không có dữ liệu trend hiện tại: câu trend chỉ là gợi ý, tự kiểm tra trước khi dùng. Mỗi lần đề xuất tính vào hạn mức Claude Code của bạn.
- `hooks.json` bị xoá khi bạn Duyệt video (video mới đã có hook in sẵn).

Cài công cụ một lần: `bash tools/install_editor_tools.sh` (FFmpeg, whisper.cpp + model, Node 22, HyperFrames). Bản `ffmpeg` thường của Homebrew thiếu bộ lọc phụ đề (libass): cần `brew uninstall ffmpeg && brew install ffmpeg-full`. App tự tìm công cụ; nếu để chỗ khác, đặt trong `.env`: `FFMPEG_PATH`, `WHISPER_CLI`, `WHISPER_MODEL` (đường dẫn, hoặc tên như `large-v3-turbo`), `WHISPER_DIR`, `EDIT_FONT` (mặc định Arial). Phiên âm tiếng Việt cần model đa ngôn ngữ (không phải `.en`); `large-v3-turbo` cho kết quả tốt nhất, `small` hay `medium` nhanh hơn. Whisper nhận lời nói chưa hoàn hảo nên luôn xem lại phụ đề trước khi xuất.

### Xoá video

Ở mục **Chỉnh sửa video**, tick ô ở góc video (hoặc **Chọn tất cả đang hiện**) rồi bấm **Xoá video đã chọn**, hoặc bấm **Xoá** trên từng video. Cả thư mục của video (video, phụ đề, bản nháp...) được chuyển vào **Thùng rác của macOS**, lấy lại được từ Thùng rác. Nếu macOS hỏi cho app điều khiển Finder (khi thư mục nằm ở ổ khác), hãy cho phép.

- Không xoá được video đã hẹn lịch (huỷ lịch trong Fanpage trước), video đã đăng mà app còn chờ tự comment, hoặc khi đang có tác vụ chỉnh sửa / hẹn lịch / huỷ lịch chạy.
- **Ghi nhớ video đã xoá:** ID, link, tiêu đề, thư mục và ngày xoá được ghi vào `removed_videos.json` (đã gitignore). Khi tải video, link của video đã xoá được bỏ qua (nhật ký ghi "đã tải và xoá ngày ...") và được xoá khỏi file .txt như link đã tải. Muốn tải lại: tick **Tải lại cả video đã xoá trước đây** ở tab Tải video, hoặc bấm **Cho tải lại** trong mục **Video đã xoá** (cuối trang Chỉnh sửa video). Tải lại xong thì video tự ra khỏi danh sách đã xoá.
- Chỉ ghi nhớ video có ID (video tải bằng app). Sổ áp dụng chung cho mọi Page. Video đã xoá trước khi có tính năng này thì app không biết.
- **Tự xoá sau khi đăng (theo từng thư mục):** mục **Thư mục**, ở thư mục muốn dọn tick **Xoá video sau khi đăng**, chọn số ngày (2 đến 365, mặc định 3) rồi bấm **Lưu tự xoá**. Cài đặt lưu trong `channel.json` của thư mục. Tiến trình nền kiểm tra 30 phút một lần và chuyển vào Thùng rác những video: đã đăng thành công; đã comment xong, không cần comment, hoặc đã quá hạn tự comment (3 ngày sau giờ đăng); giờ đăng cũ hơn số ngày đã chọn; lần hẹn giờ cũ hơn 25 giờ. Video được ghi vào danh sách Video đã xoá như khi xoá tay. Xoá lỗi thì ghi nhật ký (Nhật ký > Tự động comment) và 6 giờ sau mới thử lại. Tối thiểu 2 ngày vì giới hạn 24 giờ và số bài mỗi ngày của Page được đếm từ các video còn trong thư mục. **Thống kê bài đăng chỉ tính video còn trong thư mục**, nên đặt số ngày lớn hơn nếu muốn xem thống kê đủ 14 ngày.
- Video đã đăng nhưng Page đang tắt tự comment: sau 3 ngày (hạn tự comment) app coi như không comment nữa, xoá tay hay tự xoá đều được.

## Tải video TikTok (không logo), Rednote và nhóm theo phim

**Tải TikTok:** ở tab Tải video dán link kênh (`https://www.tiktok.com/@tenkenh`), link một video, hoặc link rút gọn `vm.tiktok.com/...`. Cách chạy giống YouTube (cùng ô thư mục, số video mới, ghi chú đồng ý, chống trùng theo ID).

- **Không logo:** app chỉ nhận bản gốc không logo mà TikTok trả về (`play_addr`) và loại hẳn bản có logo. Video nào TikTok chỉ cho bản có logo thì app bỏ qua và ghi rõ trong nhật ký, không bao giờ lưu bản dính logo.
- **Cần `curl-cffi`** để TikTok tải ổn định (đã nằm trong `requirements.txt`). Nếu nhật ký báo thiếu: `.venv/bin/pip install "yt-dlp[default,curl-cffi]"` rồi `./service.sh restart`. Kiểm tra trước một video: `.venv/bin/yt-dlp -F "<link tiktok>"` (có dòng không ghi "watermarked" là tải được không logo).
- TikTok không dùng cookie trình duyệt (cookie hay làm TikTok lỗi). TikTok đổi cách trả dữ liệu thường xuyên hơn YouTube, nếu lỗi hàng loạt hãy cập nhật yt-dlp.
- Mục "Loại nội dung" (Shorts / Video thường) chỉ áp dụng cho YouTube.
- Chất lượng tối đa theo "DOWNLOAD_MAX_HEIGHT" (mặc định 1080, tính theo cạnh ngắn nên video dọc 1080x1920 vẫn lấy bản 1080p). Trước đây bộ lọc đếm theo chiều cao nên video dọc YouTube Shorts bị tải bản 480p; bản này đã sửa.
- Chỉ tải nội dung của bạn hoặc kênh đã cho phép. Cắt từ phim, nhạc có bản quyền dễ bị Facebook gỡ hoặc hạn chế Page (nội dung không gốc).

**Tải không cần vào Fanpage:** ở màn hình chung (Tổng quan, Kết nối Fanpage, Cài đặt chung...) có tab **Tải video**. Video lưu vào thư mục bạn đặt tên và chưa thuộc Page nào (vẫn có `permission.json` và ô xác nhận quyền). Thư mục đó hiện ở Tổng quan, mục "Thư mục chưa thuộc Fanpage nào": khi muốn đăng thì chọn Page rồi bấm **Gán**, video sẽ vào Thư viện của Page. Tải không gắn Page chỉ chống trùng với các thư mục cũng chưa gán Page, và không tải thêm vào thư mục đã thuộc một Page (hãy vào Page đó để tải). Đang tải kiểu này vẫn vào được Fanpage khác.

**Dán nhiều link:** ô đường dẫn nhận nhiều link, mỗi dòng một link (trộn YouTube, TikTok, Rednote cũng được). Link trùng chỉ tải một lần; link nào lỗi thì bỏ qua, ghi vào nhật ký và các link còn lại vẫn chạy. Tối đa 1000 link mỗi lần. Có thể bấm **Mở file .txt chứa link** (hộp chọn file của macOS) để nạp link từ file vào ô. **Tự dọn file .txt:** link đã tải xong, đã có từ trước, hoặc bài đã kiểm tra là không có video/ảnh nào để tải sẽ được xoá khỏi file ngay khi xong (dòng chỉ bị xoá khi mọi link trong dòng đã xong; dòng không có link giữ nguyên; nạp nhiều file thì xoá ở đúng file chứa link; cùng một video có hai dạng link thì cả hai dòng đều được xoá). Link kênh/danh sách, link lỗi, link bỏ qua vì không đúng loại đã chọn và link chưa mở tới đều giữ lại. Nếu hộp chọn file của macOS không mở được, app mở file bằng trình duyệt và không tự xoá link. **Báo link lỗi:** cuối lượt tải, nhật ký và khung bên dưới liệt kê từng link lỗi kèm lý do (bấm để mở, có nút chép cả danh sách) để bạn tự kiểm tra. **Bỏ qua link đã tải và dừng khi đủ số:** ô "Số video mới cần tải" là số video MỚI. Link một video đã có trong thư mục thì bỏ qua ngay, không mở lại trang; app chỉ mở link cho đến khi đủ số cần tải (link còn lại không được mở, trừ khi có video lỗi và còn thiếu). Ví dụ dán 100 link, đặt 10: bỏ qua những link đã tải, tải đúng 10 video mới rồi dừng. Đặt 0 để tải tất cả link mới. **Tự dừng khi bị chặn:** Rednote báo cần đăng nhập/xác minh (hoặc chuyển sang trang đăng nhập) thì app dừng ngay ở link đó; lỗi khác mà 3 link liên tiếp không mở được cũng dừng, báo trong nhật ký và thông báo, không mở tiếp các link còn lại để tránh bị khóa tài khoản; giữa hai lần mở bài Rednote app nghỉ 1–2,5 giây. Mở thử một bài trong trình duyệt, đợi một lúc rồi tải lại (link đã tải sẽ được bỏ qua).

**Rednote (Xiaohongshu):** chỉ tải theo link từng bài, không tải theo trang cá nhân (yt-dlp không đọc được danh sách bài của một người). Dạng nhận được: `xiaohongshu.com/explore/<id>`, `/discovery/item/<id>` (cả tên miền `rednote.com`, link chia sẻ từ web hay dùng; app tự đổi sang xiaohongshu.com để yt-dlp đọc được), bài mở từ trang cá nhân, và link rút gọn `xhslink.com` (kể cả khi bạn dán nguyên đoạn "chia sẻ" từ app, app tự lấy link trong đó).

- **Cookie đăng nhập:** Rednote hay đòi đăng nhập hoặc xác minh. Đăng nhập Rednote trên Chrome (hoặc Safari, Firefox) ở máy này, rồi ở Cài đặt chung > Chung điền ô **Rednote: trình duyệt đã đăng nhập** (ví dụ `chrome`). Có thể điền đường dẫn file `cookies.txt` thay cho tên trình duyệt (yt-dlp có thể ghi cập nhật lại file này). Cookie chỉ được đọc trên máy bạn để mở bài, không gửi đi đâu và không bao giờ ghi vào nhật ký. Cài đặt này tách riêng với cookie YouTube.
- Link nên giữ nguyên phần `?xsec_token=...` nếu có. Rednote không trả ngày đăng nên tên thư mục video dùng ngày tải. Thư mục mặc định là `Rednote` nếu bạn không đặt tên.
- **Lấy link cả trang cá nhân (script tự chạy):** app không đọc được danh sách bài của một người, nên dùng script `tools/rednote_collect_links.js` (ở tab Tải video, mục "Rednote: lấy link cả trang cá nhân" có nút **Chép script** để khỏi mở file). Đăng nhập Rednote trên Chrome, mở trang cá nhân (của bạn hoặc người cho phép), mở Console (F12; nếu Chrome chặn dán thì gõ `allow pasting`), dán nguyên nội dung file rồi Enter. Script cuộn chậm đến cuối trang, gom link và hiện nút **Chép** (mỗi nút 100 link) để dán vào tab Tải video; cũng có nút tải file `.txt`. Script chỉ đọc link trên trang, không gửi dữ liệu đi, không đọc cookie. Trang có hàng trăm bài thì chia làm nhiều lần tải, đừng tải dồn dập.
- **Chọn Ảnh / Video / Toàn bộ:** ô **Nội dung (Rednote)** ở tab Tải video: *Toàn bộ* (mặc định) tải video và lưu ảnh của bài ảnh; *Chỉ video* bỏ qua bài ảnh; *Chỉ ảnh* chỉ lưu ảnh và bỏ qua bài video (không cần yt-dlp, chỉ mở trang bài một lần). Bài bị bỏ qua vì khác loại không tính là lỗi và được đếm riêng ở dòng kết quả. YouTube và TikTok bỏ qua ô này.
- **Bài chỉ có ảnh:** nếu bài Rednote không có video, app lưu toàn bộ ảnh vào `<thư mục>/<ngày - tiêu đề [id]>/images/` (01, 02, 03... đúng thứ tự, giữ định dạng gốc webp/jpg/png) kèm `title.txt`, `description.txt`, `hashtags.txt`, `meta.json` (`"type": "images"`). Ảnh lấy từ CDN của Rednote bằng phiên đăng nhập của bạn, là bản trang web hiển thị (không logo app). Bài ảnh **không hiện trong Thư viện** (Thư viện chỉ có video) và không hẹn giờ đăng được; thư mục dùng làm tư liệu. Tính vào "Số video mới cần tải", chống trùng theo ID, và chế độ MP3 bỏ qua bài ảnh.
- Video thường lấy từ luồng của trang web (không logo) và thử lấy cả file gốc. Nếu Rednote đòi xác minh (captcha) thì app báo lỗi rõ: mở thử bài đó trong trình duyệt để xác minh rồi tải lại. Đừng tải dồn dập, Rednote có thể khóa tạm tài khoản.
- Video tiếng Trung: dùng Chỉnh sửa video để tạo phụ đề (chọn ngôn ngữ Trung) rồi dịch sang tiếng Việt. Tiêu đề dạng `第12集` cũng được nhận là tập 12 khi nhóm theo phim.

**Nhóm theo phim:** app đọc tiêu đề để biết phim và số tập: `Tên phim | Tập 12`, `Tập 5: Tên phim`, `Tên phim (7/30)`, `Ep 3`, `E07`, `Phần 2 Tập 4` (Phần/Mùa = mùa 2), `Tập cuối`. Bỏ dấu, hoa thường, chữ "Phim" đứng đầu không làm tách nhóm.

- Ở Thư viện tick **Nhóm theo phim**: mỗi phim một khung có số video, khoảng tập, **tập còn thiếu** và **tập bị trùng** (tính trên mọi video của phim, kể cả khi bạn đang lọc tab khác). Trong khung xếp đúng thứ tự tập. **Chọn cả phim** chọn các tập theo thứ tự tập (bấm lần nữa để bỏ chọn); **Đổi tên phim** gộp hoặc sửa tên cho cả phim.
- Mỗi video có nhãn **Tập N** và nút **Sửa phim / tập** khi app nhận sai (lưu vào `series.json` trong thư mục video, thắng cả tiêu đề; để trống = quay về tự nhận). Video không có số tập thì nằm ở nhóm "Chưa nhận ra phim / tập".
- Hẹn giờ có thêm thứ tự đăng **Theo thứ tự tập (phim nhiều tập)**: tập nhỏ đăng trước, phim nào bạn chọn trước thì đứng trước.
- Gợi ý khi hẹn nhiều phim cùng lúc: hẹn xen kẽ các phim thì tập 2 có thể đăng sau tập 1 nhiều giờ; nếu muốn tập liên tiếp, đặt khoảng cách giờ nhỏ và hẹn từng phim một.

## Kho video còn đủ mấy ngày

Mỗi thẻ Page ở Tổng quan có dòng **Kho** cho biết số video chưa lên lịch (không tính video không đạt yêu cầu Reels), mỗi ngày Page đăng bao nhiêu bài theo quy tắc của Page (khung giờ, ngày nghỉ), và tổng cộng Page còn bài để đăng trong bao nhiêu ngày. Con số này gồm lịch đã hẹn (tính đến bài hẹn xa nhất) cộng số ngày kho chưa hẹn đủ dùng.

- Màu đỏ khi còn ít hơn **LOW_STOCK_DAYS** ngày (mặc định 3, đổi ở Cài đặt chung > Thông báo), vàng khi dưới 7 ngày. Khi có Page đỏ, đầu trang Tổng quan hiện khung nhắc "Sắp hết video".
- Page chưa có khung giờ đăng thì app chưa tính được kho. Page chưa có video nào thì không nhắc.
- Mỗi giờ app kiểm tra một lần, nếu có Page đỏ thì báo qua kênh thông báo (không báo lặp quá 1 lần mỗi 20 giờ cho cùng một Page).

## Kiểm tra video đạt yêu cầu Reels

Trước khi hẹn giờ, app dùng `ffprobe` (đi kèm ffmpeg) đọc từng video và so với yêu cầu Reels của Meta:

| Mức | Điều kiện |
|---|---|
| Không đạt (video bị bỏ qua khi hẹn giờ, không tốn lượt giới hạn 24 giờ) | độ dài dưới 3 giây hoặc trên 90 giây; độ phân giải dưới 540x960; file hỏng không đọc được |
| Cần xem lại (vẫn hẹn được, có ghi chú trong nhật ký) | không phải khung dọc 9:16; rộng dưới 720 px; dưới 24 hoặc trên 60 khung hình/giây; không có âm thanh |

- Video vừa tải xong được kiểm tra luôn, kết quả hiện thành nhãn trên thẻ video ("Không đạt yêu cầu Reels", "Cần xem lại (Reels)"). Rê chuột vào nhãn để xem lý do. Video không đạt không chọn được và bị loại khi bấm "Chọn đủ cho...".
- Nút **Kiểm tra Reels** (tab Thư viện) kiểm tra các video chưa lên lịch của Page; giữ **Shift** khi bấm để kiểm tra lại từ đầu. Kết quả lưu trong `reels_check.json` của từng thư mục video và tự làm mới khi file video đổi.
- Chưa cài ffprobe thì bước này tự bỏ qua và nhật ký có ghi chú. Muốn tắt hẳn: Cài đặt chung > Chung, "Kiểm tra video đạt yêu cầu Reels" chọn Tắt (hoặc `REELS_CHECK=0`).
- Đây là kiểm tra theo tài liệu công khai của Meta. Facebook vẫn có thể từ chối video vì lý do khác (ví dụ bản quyền nhạc).

## Thông báo sự cố (macOS và Telegram)

Khi có sự cố, app gửi thông báo để bạn khỏi phải mở giao diện kiểm tra. Cài đặt chung > **Thông báo**.

Các sự cố được báo:
- Page bị Facebook giới hạn tần suất (app đã tự dừng hẹn giờ và comment của Page đó).
- Bài đăng bị lỗi hoặc không còn trên Facebook.
- Comment thất bại sau 6 lần thử, hoặc quá 3 ngày mà chưa comment được.
- Page sắp hết video.
- Tải video bị dừng vì 10 video liên tiếp lỗi.

Cùng một sự cố không bị báo lặp (trong 6 đến 24 giờ tùy loại); trạng thái chống lặp lưu ở `notify_state.json`. Nếu lúc gửi bị lỗi mạng, lần kiểm tra sau sẽ thử lại.

**Thông báo macOS**: bật sẵn (`NOTIFY_MAC`). Nếu bấm Gửi thử báo OK mà không thấy banner, vào Cài đặt hệ thống > Thông báo, bật cho **Script Editor** (hoặc Terminal, tùy máy) và tắt chế độ Không làm phiền.

**Telegram** (nhận được cả khi không ở cạnh máy):
1. Trong Telegram, nhắn **@BotFather**, gửi `/newbot`, đặt tên. BotFather trả về token dạng `123456789:AA...`.
2. Mở bot vừa tạo, bấm **Start** (hoặc nhắn một tin bất kỳ). Muốn nhận trong nhóm thì thêm bot vào nhóm rồi nhắn một tin trong nhóm.
3. Trong app: dán token vào ô **Token bot Telegram**, bấm **Tự lấy chat ID** (app tự lưu token và điền chat ID), rồi bấm **Gửi thử**.

Token bot lưu trong `.env`, giao diện không hiện lại và lỗi kết nối được che token. Không đưa token này lên chat hay GitHub.

## Giới hạn tần suất của Facebook

Có hai loại giới hạn khác nhau, app xử lý cả hai:

1. **Giới hạn đăng của từng Page** (spam): hẹn giờ quá nhiều video trong thời gian ngắn thì Facebook có thể chặn tạm thời Page với thông báo "Để bảo vệ cộng đồng khỏi spam, chúng tôi giới hạn tần suất bạn đăng bài...".
2. **Giới hạn lượt gọi API của cả app**: thông báo "(#4) Application request limit reached" (hoặc code 17, 613). Xem mục ngay bên dưới.

### Giới hạn lượt gọi API của cả app (tránh "Application request limit reached")

Mỗi thao tác chạm Facebook (hẹn giờ, huỷ, đổi giờ, kiểm tra trạng thái, comment, kiểm tra token) là một hoặc vài lượt gọi Graph API. Theo tài liệu của Meta, mức cơ bản là khoảng **200 lượt × số người dùng của app trong mỗi 60 phút (cửa sổ trượt)**, tính cho cả app chứ không riêng từng Page; ngoài ra mỗi Page còn một hạn mức riêng theo 24 giờ. Vượt mức thì Facebook trả lỗi code 4 / 17 / 613 và khóa app khoảng một giờ; tài liệu dặn **dừng gọi** khi bị khóa vì gọi tiếp chỉ kéo dài thời gian khóa. Meta không công bố hạn mức thực tế của từng app, nên app tự đếm và chừa dư.

Mọi lệnh gọi Facebook đều đi qua một cổng duy nhất (`core/fbgate.py`) nên mọi tính năng, kể cả tính năng thêm sau này, bị giới hạn như nhau:

- **Ngân sách theo giờ:** mặc định tối đa **150 lượt trong 60 phút qua** (Cài đặt chung > Chung > "Số lượt gọi Facebook tối đa mỗi giờ", từ 20 đến 5000). Số đếm lưu trong `fbgate_state.json` nên tắt/mở lại app không làm số đếm về 0. Hết ngân sách thì lệnh kế tiếp bị từ chối ngay, **không gọi Facebook**, kèm số phút phải chờ.
- **Việc chạy nền không chiếm chỗ của bạn:** kiểm tra trạng thái tự động tối đa 25% ngân sách, kiểm tra tự động cộng comment tối đa 60%; phần còn lại luôn dành cho thao tác của bạn. Nút **Kiểm tra trạng thái** (hàng loạt) luôn chừa lại 25% ngân sách cho hẹn giờ, huỷ, comment.
- **Giãn nhịp:** khoảng 0,6 giây giữa hai lệnh; chậm gấp ba cho việc chạy nền và khi đã dùng từ 70% ngân sách. Không bao giờ bắn dồn dập.
- **Đọc mức dùng thật từ Facebook:** mỗi phản hồi có header `X-App-Usage`, `X-Business-Use-Case-Usage`... Facebook báo đã dùng từ 85% hạn mức thì app tự dừng 10 phút **trước khi** bị chặn (việc mới bị chặn; một lần hẹn giờ đã bắt đầu tải lên thì vẫn được làm nốt để không bỏ dở); Facebook báo thời gian chờ (`estimated_time_to_regain_access`) thì dừng đúng bằng thời gian đó.
- **Khi Facebook đã báo giới hạn** (code 4, 17, 613, 80000 đến 80014, hoặc HTTP 429): app dừng **mọi** lệnh gọi Facebook 60 phút (hoặc đúng thời gian Facebook báo, nếu dài hơn) và gửi một thông báo. Trong lúc dừng, huỷ, hẹn giờ, kiểm tra, comment đều báo "chưa làm gì" thay vì thử lại; tự động comment và kiểm tra nền tự ngừng và tự chạy lại khi hết thời gian. Giới hạn riêng của một Page (code 32, 368) vẫn xử lý riêng như loại 1.
- **Hết lượt giữa chừng thì dừng gọn, không để lệch:** huỷ hàng loạt dừng đúng lúc, các bài chưa huỷ giữ nguyên; hẹn giờ chỉ xếp số video còn đủ lượt (mỗi video 3 lượt: bắt đầu, tải lên, hoàn tất) và phần còn lại để lần sau; "huỷ rồi hẹn lại" kiểm tra đủ lượt cho cả hai bước **trước khi** xóa bài cũ; comment bị hoãn sang vòng sau mà không tính là một lần thử thất bại; kiểm tra trạng thái hàng loạt dừng và báo đã kiểm tra bao nhiêu video.
- **Nhìn thấy được:** chip **Facebook: 42/150** ở đầu trang (xanh dưới 70%, vàng từ 70%, đỏ khi hết lượt hoặc đang dừng). Bấm vào để xem chi tiết (bạn thao tác, kiểm tra nền, comment, mức Facebook báo, thời gian dừng). Nút **Bỏ trạng thái dừng** chỉ nên dùng khi bạn chắc Facebook đã hết giới hạn.

Chi phí ước tính cho mỗi video: hẹn giờ 3 lượt, huỷ 1 (thêm 1 nếu bài đã quá giờ hẹn, vì app hỏi trạng thái trước), đổi giờ 1, kiểm tra trạng thái 1, comment 1 đến 2. Với 150 lượt/giờ, một giờ huỷ được khoảng 150 bài hoặc hẹn được khoảng 50 video; nhiều hơn thì chia thành các đợt cách nhau (app báo rõ còn bao nhiêu và chờ bao lâu).

Khoảng nghỉ giữa hai lệnh có thể chỉnh bằng biến `FB_MIN_INTERVAL_SECONDS` trong `.env` (mặc định 0.6, tối đa 10).

### Giới hạn đăng của từng Page

Để tránh bị chặn vì đăng quá dày, app có:

- **Giới hạn mỗi 24 giờ** (mặc định 30 video cho mỗi Fanpage, đặt ở Cài đặt chung > Mặc định Page hoặc riêng cho từng Page ở tab Cài đặt Page; Facebook tính khoảng 30 bài đăng qua API mỗi 24 giờ). Chọn nhiều hơn mức còn lại thì app chỉ xếp phần vừa đủ và để phần còn lại cho lần sau. Đặt 0 để tắt giới hạn.
- **Nghỉ giữa hai video** (mặc định khoảng 15 giây, có ngẫu nhiên thêm).
- **Tự dừng khi bị chặn**: app dừng ngay, ghi nhận Page đang bị giới hạn (hiện ở Tổng quan, thanh phía trên Page và khung Lên lịch), không hẹn thêm và tạm dừng tự động comment của Page đó, mặc định 24 giờ. Facebook không công bố thời gian chặn cụ thể, thường là một đến hai ngày. Nếu chắc chắn đã hết bị chặn, bấm **Bỏ cảnh báo** ở tab Cài đặt Page hoặc Kết nối Fanpage.

Nếu bị chặn: đừng thử lại liên tục, đợi vài giờ đến một hai ngày, và giảm tần suất đăng và comment.

## Nội dung bài đăng

Mỗi bài đăng lấy nội dung theo thứ tự:

1. `caption.txt` nếu bạn đã sửa tay trong app (nút **Sửa nội dung**).
2. Nếu không thì dùng **mô tả** của video (`description.txt`), thường đã chứa tiêu đề và hashtag.
3. Mô tả trống thì dùng tiêu đề (`title.txt`).

App không ghép thêm hashtag từ `hashtags.txt` (file đó còn chứa các thẻ ẩn của YouTube). Chỉ khi nội dung hoàn toàn không có hashtag, app mới thêm tối đa 5 hashtag ngắn.

**Giới hạn hashtag:** nội dung lấy từ mô tả hoặc tiêu đề chỉ giữ tối đa **5 hashtag đầu tiên**; thẻ trùng (không phân biệt hoa thường, kể cả dính liền như `#a#a`) bị bỏ và không tính vào 5. Thẻ nằm giữa câu mà bị bỏ thì chỉ mất dấu `#`, chữ vẫn còn. Link và chữ như `C#` không bị đụng. Caption bạn tự sửa tay (`caption.txt`) giữ nguyên, không cắt. Đổi mức giới hạn bằng `MAX_HASHTAGS` trong `.env` (0 = không giới hạn). Bài đã hẹn từ trước không bị đổi, chỉ áp dụng cho bài hẹn sau này. Nút **Khôi phục mặc định** trong hộp sửa sẽ xóa `caption.txt`.

## Trạng thái đăng thật

Hẹn giờ thành công chưa có nghĩa là bài đã lên. App hỏi Facebook và hiện trên thẻ video:
- **Đã đăng** (kèm link "Xem bài trên Facebook"), **Lỗi đăng**, **Không thấy trên Facebook**, **Quá giờ chưa đăng** (quá giờ hẹn 15 phút mà Facebook vẫn báo chưa đăng), hoặc giờ hẹn nếu chưa đến giờ.
- App tự kiểm tra các video đã đến giờ hẹn (mỗi vài phút, khi app đang chạy). Video chưa đến giờ thì app không tự hỏi Facebook, để đỡ tốn lượt gọi.
- Nút **Kiểm tra trạng thái** trong Thư viện hỏi Facebook **lần lượt từng video đã hẹn của Page đang chọn** (kể cả chưa đến giờ, bỏ qua bài đã đăng; không giới hạn số lượng). Việc chạy nền như một tác vụ: thanh thông báo hiện tiến độ "đã kiểm tra X/Y", đóng cửa sổ vẫn chạy tiếp, xem chi tiết và bấm dừng ở tab Nhật ký. Xong thì báo tổng kết, ví dụ "Đã kiểm tra 40/40 video: 35 chờ đến giờ, 3 đã đăng, 2 không thấy trên Facebook". Dùng nút này sau khi bạn xóa bài hẹn trực tiếp trên Facebook: bài đã xóa thành "Không thấy trên Facebook" (tab Lỗi / quá giờ), chọn rồi bấm **Hẹn lại** để đưa về Chưa lên lịch. Nếu 5 video liên tiếp không đọc được trạng thái (mất mạng hoặc token hỏng) thì app dừng sớm và báo. Bài hẹn chưa đến giờ mà biến mất không gửi thông báo, vì app coi đó là bạn chủ động xóa.
- Bộ lọc có thêm "Đã đăng" và "Lỗi / quá giờ chưa đăng".
- **Hẹn lại**: với video "Lỗi đăng" hoặc "Không thấy trên Facebook", nút này gỡ lịch cũ trong app (giữ bản cũ ở `scheduled.old.json`) để bạn chọn và hẹn lại. App không xóa gì trên Facebook, nên hãy kiểm tra Meta Business Suite trước để tránh đăng trùng, vì "Không thấy" cũng có thể do token thiếu quyền đọc.
- Tự động comment chỉ gửi khi Facebook xác nhận bài đã đăng. Bài lỗi thì bỏ qua comment ("Không comment (bài lỗi)"). Bài đã bị xóa trên Facebook cũng không comment ("Không comment (bài đã xóa)"): app nhận ra khi kiểm tra trạng thái, hoặc ngay khi Facebook trả lời "không tồn tại" lúc comment; khi đó không thử lại 6 lần, không báo "Comment thất bại", chỉ gửi một thông báo "Bài không còn trên Facebook". Video đó nằm ở tab Lỗi / quá giờ để bạn bấm Hẹn lại nếu muốn đăng lại; nếu bài hiện lại trên Facebook thì app comment tiếp. Nếu app không không đọc được trạng thái, hoặc bài vẫn báo chưa đăng quá 30 phút sau giờ hẹn, app vẫn thử comment như trước.

Cách Facebook trả trạng thái Reel có thể thay đổi. Nếu bạn thấy trạng thái sai, di chuột vào nhãn để xem chi tiết rồi báo lại.

## Link affiliate riêng cho từng video

1. Trong Thư viện bấm **Tải CSV mẫu**: file có cột `video` (ID YouTube), `title` và `link` cho các video chưa lên lịch trong bộ lọc hiện tại.
2. Điền cột `link` (link Shopee...) rồi bấm **Nhập CSV link affiliate**. Cột `video` nhận ID YouTube, link YouTube, tên thư mục hoặc một đoạn tên đủ nhận ra đúng một video. App báo những dòng không khớp hoặc link không hợp lệ. Ô link trống thì bỏ qua, không xóa link cũ. Dùng được dấu `,` hoặc `;` và file lưu từ Excel.
3. Hoặc nhập từng video ở **Sửa nội dung > Link affiliate**. Link lưu trong `affiliate.txt` của video.
4. Trong kho comment (tab Cài đặt Page) dùng `{link}` để chèn link của video, ví dụ `Mua tại đây 👉 {link}`. Câu có `{link}` chỉ được dùng cho video đã có link. Câu không có `{link}` sẽ được thêm link xuống dòng cuối nếu video có link. Video không có link thì chỉ dùng các câu không có `{link}`.

## Chống trùng video

Video đã có ở một thư mục của chính Page đang làm việc (nhận theo ID YouTube) sẽ không bị tải lại. Trong một Page, một video YouTube cũng chỉ được hẹn giờ một lần, kể cả khi nó nằm ở nhiều thư mục hoặc bị chọn trùng. Page khác có kho video riêng nên có thể dùng lại cùng video nếu bạn muốn.

Video đã tải rồi **xoá** (ở mục Chỉnh sửa video) cũng không bị tải lại, ở mọi Page, vì app ghi nhớ trong `removed_videos.json`; tick **Tải lại cả video đã xoá trước đây** khi muốn tải lại (xem phần Xoá video).

## Tự động comment (link affiliate...)

App có thể tự comment vào bài ngay sau khi bài được đăng (Facebook không cho comment khi bài còn ở trạng thái hẹn giờ).

1. Token của Page cần có quyền `pages_manage_engagement` (kiểm tra bằng nút **Kiểm tra token**).
2. Mở Page, tab **Cài đặt Page**: tick **Tự động comment**, rồi ở khung **Kho comment của Fanpage** bấm **+ Thêm comment** để lưu sẵn nhiều câu (Comment 1, Comment 2, ...), bấm **Lưu kho comment**. Mỗi Page có kho comment riêng. Mỗi video, đến lúc comment app chọn ngẫu nhiên một câu trong kho, cố gắng không trùng câu vừa dùng ngay trước đó. Câu đã chọn được ghi vào `scheduled.json` nên nếu phải thử lại vẫn dùng đúng câu đó. Kho lưu trong `pages.json`.
3. Muốn comment riêng cho từng video (ví dụ mỗi video một link): bấm **Sửa nội dung** ở video đó và nhập vào ô comment. Để trống ô này thì video dùng kho comment ngẫu nhiên; gõ một dấu `-` nếu video đó không cần comment.
4. App chờ đến giờ hẹn cộng thêm vài phút (mặc định 3 phút) rồi gửi comment, các comment cách nhau ít nhất 30 giây (cả hai chỉnh được riêng cho từng Page). Nhãn trên thẻ video: "Chờ comment", "Đã comment", "Đang thử lại comment", "Lỗi comment", "Quá hạn comment".
5. App **phải đang chạy** (máy bật, không ngủ) vào lúc đó. Nếu tắt lúc đến giờ, lần mở lại app tự bù, nhưng quá 3 ngày sau giờ đăng thì bỏ qua. Nút **Comment ngay** trên thẻ video để gửi tay hoặc thử lại.
6. Lỗi tạm thời được thử lại tối đa 6 lần (cách nhau 5 đến 30 phút). Trạng thái lưu trong `scheduled.json` của từng video, nên không bao giờ comment trùng.

Lưu ý: comment giống hệt, dày đặc dễ bị Facebook coi là spam. Nên giãn giờ đăng và đổi nội dung comment cho tự nhiên, đồng thời ghi rõ đó là link affiliate.

## Cấu trúc thư mục video

```
OfflineYtb/
└── TenKenh/
    ├── permission.json                 # ghi chú sự đồng ý của chủ kênh (kênh YouTube hoặc TikTok)
    ├── channel.json                    # Fanpage sở hữu thư mục này
    └── 20261020 - Tiêu đề [videoId]/
        ├── video.mp4
        ├── title.txt
        ├── description.txt
        ├── hashtags.txt
        ├── meta.json                   # gồm cả nguồn (platform: youtube/tiktok)
        ├── series.json                 # (tùy chọn) phim/tập bạn sửa tay: {"name": "...", "episode": 5}
        ├── caption.txt                 # (tùy chọn) nội dung bài đăng bạn đã sửa tay
        ├── comment.txt                 # (tùy chọn) comment riêng của video, thay cho kho ngẫu nhiên
        ├── affiliate.txt               # (tùy chọn) link affiliate của video, thay vào {link}
        ├── scheduled.json              # có sau khi đã hẹn giờ, kèm Page, trạng thái đăng và comment
        ├── scheduled.old.json          # (tùy chọn) lịch cũ sau khi bấm Hẹn lại
        ├── subs.json                   # (tùy chọn) phụ đề của bước Chỉnh sửa, gồm cả câu gốc nếu đã dịch (xoá sau khi duyệt)
        ├── voice.mp3                   # (tùy chọn) giọng đọc của bạn (đuôi có thể khác)
        ├── edit.json                   # (tùy chọn) cài đặt lần xuất gần nhất
        ├── video.draft.mp4             # (tùy chọn) bản nháp chưa duyệt; hẹn giờ đăng chưa dùng nó
        └── edit_approved.json          # (tùy chọn) dấu đã duyệt: video.mp4 là bản đã chỉnh sửa
```

Video tải bằng script cũ nằm thẳng trong thư mục gốc vẫn hiện trong Thư viện.

## Bảo mật

- Server chỉ lắng nghe `127.0.0.1`, từ chối yêu cầu có Host lạ và yêu cầu ghi không phải JSON.
- User token nằm trong `.env`, Page token nằm trong `pages.json` (cả hai quyền 600, đã có trong `.gitignore`). Giao diện không bao giờ nhận lại giá trị token, chỉ biết "đã lưu" hay chưa.
- User token ngắn hạn hết hạn sau khoảng 1 giờ. Khi cần thêm Page mới hoặc làm mới token, dán User token mới rồi lấy danh sách lại.

## Nhật ký tác vụ được lưu lại

Mỗi tác vụ (tải video, hẹn giờ, kiểm tra Reels, cập nhật yt-dlp, tự động comment) được ghi ra file `logs/jobs/<ngày-giờ>_<mã>.jsonl` ngay khi chạy, nên tab **Nhật ký** vẫn xem được sau khi tắt hoặc khởi động lại app.

- Tác vụ đang chạy mà app bị tắt được hiện là "Lỗi: bị gián đoạn". Lần chạy sau của bạn không bị ảnh hưởng.
- Giữ tối đa 150 file và 30 ngày gần nhất, mỗi tác vụ tối đa 6000 dòng. File chỉ bạn đọc được (quyền 600) và đã che token. Thư mục `logs/` nằm trong `.gitignore`.
- Nếu chạy nền bằng `service.sh`, nhật ký của chính server (lỗi Python, yêu cầu HTTP) nằm ở `logs/server.log`, xem bằng `./service.sh logs`.

## Cập nhật yt-dlp

YouTube hay đổi nên yt-dlp bản cũ là nguyên nhân thường gặp khi tải lỗi hàng loạt. App có:

- Khối **yt-dlp** ở Cài đặt chung > Chung: hiện bản đang dùng, bản mới nhất đã biết, nút **Kiểm tra và cập nhật** (cài bằng pip vào đúng môi trường `.venv` của app; bản mới không chạy được thì tự trả về bản cũ).
- **Tự cập nhật mỗi ngày** (bật sẵn, tắt ở ô "Tự kiểm tra và cập nhật yt-dlp mỗi ngày"): chỉ chạy khi không có tác vụ nào đang chạy, lỗi thì thử lại sau 6 giờ và báo qua Telegram/macOS (một lần mỗi ngày). Cập nhật xong cũng có báo.
- **Áp dụng bản mới cần khởi động lại app.** Chạy nền bằng `service.sh`: app tự khởi động lại một lần khi rảnh sau lần tự cập nhật (launchd bật lại ngay, trang mất kết nối vài giây). Cập nhật bằng tay thì hiện nút **Khởi động lại app** để bạn chọn lúc. Chạy bằng `./run.sh`: bấm Ctrl+C rồi chạy lại.
- Khi bản yt-dlp đang dùng đã quá 45 ngày, nhật ký tải ghi nhắc cập nhật, và thông báo "Tải video bị dừng" cũng kèm nhắc này.
- Trạng thái lưu ở `ytdlp_state.json` (đã có trong `.gitignore`). Cần có mạng để hỏi PyPI.

## Gặp lỗi

- Không tải được, YouTube đòi xác minh: Cài đặt > Chung, đặt "Trình duyệt lấy cookie" là `chrome`.
- Facebook báo thiếu quyền: bấm **Kiểm tra token** (Kết nối Fanpage hoặc Cài đặt Page), thêm quyền còn thiếu trong app Meta rồi lấy token lại.
- Reel hẹn giờ nhưng người ngoài không thấy: app Meta có thể còn ở chế độ Development, cần chuyển sang Live.
- Video bị báo "Không đạt yêu cầu Reels": rê chuột vào nhãn xem lý do (thường là quá ngắn/dài hoặc độ phân giải thấp). Sửa hoặc thay video rồi bấm **Kiểm tra Reels** (giữ Shift để kiểm tra lại).
- Không thấy nút Kiểm tra Reels làm việc, nhật ký báo chưa cài ffprobe: `brew install ffmpeg`.
- Telegram "Gửi thử" báo lỗi 401 hoặc Unauthorized: token bot sai. Báo "Chưa thấy tin nhắn nào gửi cho bot": mở bot, bấm Start rồi bấm lại **Tự lấy chat ID**.
- Rednote báo "đòi đăng nhập hoặc xác minh": kiểm tra ô cookie Rednote ở Cài đặt chung, đã đăng nhập Rednote trên đúng trình duyệt đó chưa, mở thử bài trong trình duyệt rồi tải lại. Mở Chrome/Safari lần đầu có thể hiện hộp thoại cho phép đọc cookie.
- TikTok báo "chỉ trả bản có logo" hoặc lỗi impersonation: cài `curl-cffi` (xem mục Tải video TikTok), cập nhật yt-dlp, thử lại sau; TikTok hay chặn tạm thời.
- Tải video lỗi hàng loạt dù link đúng: vào Cài đặt chung > Chung bấm **Kiểm tra và cập nhật** yt-dlp, rồi khởi động lại app.
- App báo "đã dùng X/150 lượt gọi Facebook nên tự dừng" hoặc chip Facebook đỏ: đó là cổng giới hạn lượt gọi đang bảo vệ app khỏi lỗi "Application request limit reached". Đợi đúng số phút app báo rồi làm tiếp (không cần bỏ trạng thái dừng). Nếu bạn thường xuyên chạm mức này mà Facebook chưa từng báo lỗi, tăng "Số lượt gọi Facebook tối đa mỗi giờ" ở Cài đặt chung > Chung từng chút một (tối đa khoảng 200 nếu app chỉ có một người dùng).
- Đổi cổng: `PORT=8080 ./run.sh`.
- Graph API: app dùng phiên bản trong Cài đặt > Chung (mặc định v21.0, Facebook cho dùng đến 21/01/2027). Khi gần hết hạn, đổi sang v25.0 hoặc mới hơn rồi thử lại với 1 video.
