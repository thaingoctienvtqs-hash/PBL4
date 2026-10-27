# Thu thập/gán nhãn v2 — ESP32-CAM ở mép trên tranh

Đây là hướng dẫn cho lượt thu sau khi được phê duyệt riêng, **chưa thu camera trong lượt này**. Cấu hình bắt buộc: OV3660, TOP_EDGE_DIRECT, OBLIQUE_DOWNWARD. Không thay bằng camera trần/giá treo cao/đối diện tranh. Góc nghiêng, FOV, coverage và vùng mù thật chưa đo.

## 1. Phân công và lưu dữ liệu

Nhóm có thể phân công: một người vận hành luồng ESP chính, một người quay camera phụ bên hông, hai người luân phiên thao tác/gán nhãn và review chéo. Người review không dùng ALERT/score để suy ground truth. Dùng person_group_id giả danh, giữ provenance và thỏa thuận người tham gia.

Chỉ một consumer ESP32-CAM, tái sử dụng luồng lấy frame hiện có. Không mở worker AI, dashboard preview hoặc collector ESP khác cùng lúc để lấy thêm frame. Không tự tăng resolution/FPS, đổi firmware hoặc camera setting. Camera phụ là thiết bị độc lập, chỉ cung cấp ground truth.

Lưu raw JPEG/video trước overlay, giữ nguyên dữ liệu gốc. Mỗi session/video/segment có path/hash, source, camera, artwork, capture_group, split và measurement notes. Không ghi vào dataset ContactHands, checkpoint, runtime evidence hoặc database. Tạo thư mục thu mới khi được duyệt riêng.

## 2. Clock và đồng bộ

Ghi frame_id, source_frame_id nếu nguồn thật có, sequence_index, kích thước, host_receive_timestamp_ms và clock ID. Capture timestamp không có từ thiết bị thì null/status UNKNOWN; timestamp_basis=HOST_RECEIVE_ONLY hoặc UNKNOWN đúng thực tế.

Với HTTP /capture, thời gian nhận không phải thời gian sensor chụp. Không suy từ filename, file mtime, FPS danh nghĩa hoặc video dựng từ JPEG. Request timing/buffer age nếu thu được chỉ là provenance, không chứng minh capture time khi chưa kiểm tra driver/camera.

Dùng tín hiệu nhìn thấy ở cả hai camera, đầu và cuối đoạn; tín hiệu không được che vùng tiếp xúc hoặc đòi thay firmware. Ghi sync ID, primary anchor, offset theo quy ước reference=primary+offset tại anchor và sai số đo. Kiểm tra drift trên segment; nếu không đủ đồng bộ, giữ UNKNOWN hoặc chia segment/giảm phạm vi kết luận.

Không đo được capture clock hoặc không liên kết side video với timeline chính đáng tin cậy thì không báo capture-to-alert latency. Có thể gán nhãn theo frame/quan sát với biên thời gian null; không tạo thời gian capture giả.

## 3. Pilot đề xuất

12 phiên x 6–8 phút, khoảng 72–96 phút; đề xuất 4 validation, 8 test. Đây là pilot cho tính khả thi, **chưa khẳng định đủ chứng minh Accuracy >80%**.

Phân bố qua nhiều người, tốc độ, ánh sáng mạnh/yếu/bóng đổ và vùng gần/giữa/xa camera. Giữ vị trí lắp đúng mép trên; mọi thay đổi góc sau này cần phiên/calibration mới. Tách người giữa validation/test nếu khả thi; nếu không, ghi rõ giới hạn.

Mỗi phiên có các đoạn biết rõ mục đích và khoảng nghỉ không có tay. Phải có cả positive và hard negatives:

| Nhóm | Ca cần thu |
|---|---|
| Tiếp cận | Tay từ ngoài đến chạm; tay xuất hiện lần đầu ngay trong ROI |
| Khoảng hở | Tay rất gần nhưng dừng trước chạm; đi ngang không chạm |
| Chuyển động | Đi chậm dọc mặt tranh có/không chạm, đổi hướng/tốc độ |
| Contact ngắn/dài | Chạm nhanh rút ra; chạm rồi giữ yên; nhiều episode |
| Nhiều tay | Hai tay, giao nhau, che nhau, tay cũ rời/tay khác thay thế |
| Tay in | Tranh có hình bàn tay, chỉ tay in, tay thật đi qua vùng đó |
| Vật khác | Tay cầm vật khác trước tranh nhưng không chạm tranh |
| Camera/ảnh | Rung nhẹ có kiểm soát, ánh sáng/bóng đổi, blur, offline/reconnect |
| Vùng quan sát | Gần/giữa/xa; ngoài FOV và chỗ không nhìn được khoảng hở |

Không thử chạm/rung trên tác phẩm có nguy cơ hư hại; nhóm chọn bề mặt thử nghiệm được phép. Video quay thật trên bản in thử phải được ghi đúng là setup thử nghiệm, không gọi là dữ liệu bảo tàng thật.

Giữ các frame mất tự nhiên trong acquisition log. Các bài drop 1/nhiều frame hoặc đổi sampling rate về sau chỉ replay trên bản sao có manifest; không làm ESP mất gói bằng tăng tải. Không upsample/nhân bản 1 FPS thành 30 FPS rồi gọi là thử nghiệm thực.

Để đo false alerts/hour có ý nghĩa, bổ sung các đoạn no-contact dài ở nhiều phiên. 0 false alert trong vài phút không chứng minh tỷ lệ ngoài thực tế thấp.

## 4. Hiệu chuẩn và vùng mù

Dùng CALIBRATION_CHECKLIST.vi.md. ROI chỉ chứa phần mặt tranh thật thấy được, normalized theo đúng ảnh nguồn. Camera gần mép trên có thể nhìn thiếu tranh hoặc vùng xa bị nén; lưu coverage PARTIAL/UNKNOWN, không lấy full image.

Vùng ngoài FOV chưa biết kích thước thì coordinates=null, coordinate_space UNKNOWN. Vùng nhìn thấy nhưng tay quá nhỏ/mờ phải ghi LOW_RESOLUTION hoặc nhận xét quan sát, không ngầm coi đã bảo vệ đầy đủ.

Reference frame không có tay thật. Không coi tay thật đứng yên là tay in/nền; không co ROI khi tay che. Camera move/đổi ảnh source cần barrier/calibration mới, không chuyển entry/history bằng annotation.

## 5. Gán nhãn

Hai reviewer xem raw clip chính và reference bên hông. Lưu nguồn và bằng chứng:

- TOUCH: xác minh tay thật chạm đúng bề mặt tranh.
- NEAR_NO_TOUCH: xác minh có khoảng hở, ghi near_definition đã thống nhất trước. Không ước lượng mm từ bbox.
- NO_TOUCH: xác minh không có contact trong scope/interval đã review; có thể không có tay.
- UNKNOWN: che khuất, không đồng bộ, hình không rõ hoặc bất đồng không giải quyết được.

UNKNOWN không phải NO_TOUCH. Object-Contact cao có thể do tay cầm đồ khác; không dùng score/overlap/ALERT làm GT.

Gán hand_id theo bàn tay vật lý trong session; hai tay cùng người khác ID. Depicted hand dùng depiction_id và không có physical hand_id. Occlusion FULL thì bbox=null, không vẽ vị trí ẩn. Khi không biết identity thì null/UNCERTAIN; không ép ghép.

Ghi frame/video refs và interval [start,end) theo clock chính, uncertainty của biên; không biết timestamp để null. Lưu khoảng NO_TOUCH/UNKNOWN có scope SCENE, còn contact của từng tay scope HAND. Hai tay có thể mang nhãn khác nhau đồng thời.

Re-ID chỉ gán ở block tùy chọn, gallery trước gap, query sau gap, cùng phiên. Không có tay/gap/pair vẫn là annotation hợp lệ. Không tạo cặp để thỏa schema.

## 6. Split, kiểm tra và điều kiện bàn giao

Mọi clip/segment/frame/crop/pair từ cùng phiên hoặc nguồn liên tục/capture_group phải cùng split; không random frame. Chặn bản sao/near-duplicate giữa split bằng review nguồn và kiểm tra phù hợp. Khóa test và hash trước chỉnh tham số.

Các CSV mới chỉ header; list/object nhập dạng JSON có quoting đúng. Bundle JSON là nguồn chuẩn. Không tự sửa v1; xem SCHEMA_AND_MIGRATION.vi.md.

Trước bàn giao: validate cấu trúc + semantics; kiểm tra asset/hash thực; reviewer phê duyệt; ghi đoạn thiếu timestamp/sync/coverage/GT. Thư viện jsonschema chưa có thì báo formal validation chưa chạy, không tự cài.

Thu dữ liệu không tự cho phép chạy inference GPU hoặc thay AI. Mọi số liệu model vẫn CHƯA ĐÁNH GIÁ đến khi có prediction thật và scorer độc lập.
