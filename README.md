# Quản lý video

Ứng dụng web chạy trên máy bạn (http://127.0.0.1:5173), quản lý nhiều Fanpage theo kiểu mỗi Page là một không gian làm việc riêng, giống Meta Business Suite.

**Mở app là vào trang Tổng quan**: mỗi Fanpage là một thẻ cho biết hôm nay đã hẹn mấy bài (so với số bài mỗi ngày của Page), bao nhiêu video chờ đăng, chưa lên lịch, đã đăng, lỗi, đã hẹn bao nhiêu trong 24 giờ qua, bài kế tiếp, **kho video còn đủ đăng mấy ngày** (chuyển đỏ khi sắp hết) và trạng thái bị Facebook giới hạn. Bấm **Mở Page** để vào làm việc với Page đó. Trong Page, thanh phía trên có **← Tổng quan** để quay về và ô **Đang làm việc với Fanpage** để chuyển sang Page khác. Mọi thứ bên dưới chỉ thuộc về Page đang chọn:

1. **Tải video** từ kênh YouTube đã đồng ý cho bạn dùng, lưu vào thư mục đặt tên (thư mục đó thuộc Page đang chọn), kèm tiêu đề, mô tả, hashtag.
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

## Mỗi thư mục thuộc một Fanpage

- Mỗi thư mục kênh (ví dụ `OfflineYtb/TenKenh`) thuộc đúng một Fanpage, ghi trong file `channel.json` của thư mục (`{"page_id": "..."}`). Thư mục tải về từ một Page tự thuộc Page đó. Tải cho Page khác vào thư mục đang thuộc Page này sẽ bị từ chối, hãy đặt tên thư mục khác.
- Khi nâng cấp từ bản cũ, thư mục nào mà mọi video đã hẹn trong đó đều của cùng một Page thì tự gán cho Page đó (video cũ chưa ghi Page tính là của Page cũ duy nhất). Thư mục chưa hẹn video nào, hoặc có video hẹn cho nhiều Page, hiện ở khung **Thư mục chưa thuộc Fanpage nào** trên trang Tổng quan để bạn chọn Page rồi bấm **Gán**. Thư mục chưa gán không hiện trong Thư viện của Page nào.
- Không thể hẹn video của thư mục thuộc Page khác, và không thể đổi Page của thư mục đang có video đã hẹn cho Page khác. Xóa một Page khỏi app thì các thư mục của nó thành "chưa gán".
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
    ├── permission.json                 # ghi chú sự đồng ý của chủ kênh
    ├── channel.json                    # Fanpage sở hữu thư mục này
    └── 20261020 - Tiêu đề [videoId]/
        ├── video.mp4
        ├── title.txt
        ├── description.txt
        ├── hashtags.txt
        ├── meta.json
        ├── caption.txt                 # (tùy chọn) nội dung bài đăng bạn đã sửa tay
        ├── comment.txt                 # (tùy chọn) comment riêng của video, thay cho kho ngẫu nhiên
        ├── affiliate.txt               # (tùy chọn) link affiliate của video, thay vào {link}
        ├── scheduled.json              # có sau khi đã hẹn giờ, kèm Page, trạng thái đăng và comment
        └── scheduled.old.json          # (tùy chọn) lịch cũ sau khi bấm Hẹn lại
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
- Tải video lỗi hàng loạt dù link đúng: vào Cài đặt chung > Chung bấm **Kiểm tra và cập nhật** yt-dlp, rồi khởi động lại app.
- App báo "đã dùng X/150 lượt gọi Facebook nên tự dừng" hoặc chip Facebook đỏ: đó là cổng giới hạn lượt gọi đang bảo vệ app khỏi lỗi "Application request limit reached". Đợi đúng số phút app báo rồi làm tiếp (không cần bỏ trạng thái dừng). Nếu bạn thường xuyên chạm mức này mà Facebook chưa từng báo lỗi, tăng "Số lượt gọi Facebook tối đa mỗi giờ" ở Cài đặt chung > Chung từng chút một (tối đa khoảng 200 nếu app chỉ có một người dùng).
- Đổi cổng: `PORT=8080 ./run.sh`.
- Graph API: app dùng phiên bản trong Cài đặt > Chung (mặc định v21.0, Facebook cho dùng đến 21/01/2027). Khi gần hết hạn, đổi sang v25.0 hoặc mới hơn rồi thử lại với 1 video.
