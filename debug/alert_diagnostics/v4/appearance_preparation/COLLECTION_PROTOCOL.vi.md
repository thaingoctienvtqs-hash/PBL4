# Quy trình thu thập và gán nhãn — chưa thực thi

## 1. Điều kiện bắt đầu

Cần phê duyệt riêng việc thu thập camera hoặc tiếp nhận video có sẵn, không tăng tải ESP32-CAM trong lượt này. Ưu tiên một consumer camera hiện có; không mở thêm luồng /capture. Không sửa firmware, môi trường hoặc collector hiện có. Dùng thư mục dữ liệu mới được duyệt; raw file bất biến, SHA-256, không ghi đè.

Xin phép người tham gia; dùng mã person_group_id giả danh, không tên thật. Không đặt mặt người/PII vào schema. Giới hạn quyền truy cập và thời gian giữ dữ liệu theo thỏa thuận nhóm. Đây là dữ liệu tay có thể nhận dạng tương đối, cần giữ nguyên nguồn và provenance.

## 2. Nội dung mỗi phiên

Ghi session_id, capture_group_id (mọi clip liên tục/cùng nguồn), camera_id, artwork_id, nhóm người, đường dẫn raw video hoặc manifest frame, SHA-256, kích thước, clock_id. Session/capture_group phải mới khi reset clock, camera thay vị trí hoặc ngắt phiên. Ghi ROI version, ánh sáng, góc nhìn, nguồn timestamp.

Dùng timestamp đo thực tế/PTS của video. Nếu chỉ có thời gian nhận thì ghi riêng received_timestamp_ms; không gọi là capture time. Không lấy mtime, chữ timestamp overlay hay index/FPS danh nghĩa làm thời gian thật. Ghi duplicate, corrupt, missing, offline theo quan sát; không chèn frame giả để lấp khoảng trống. Capture và processing time phải phân biệt; độ trễ end-to-end chỉ báo khi clock có thể đối chiếu.

Giữ raw ảnh trước overlay. Ảnh evidence đã có overlay chỉ dùng kiểm tra bằng mắt; không chỉnh/inpaint để biến thành raw. Không crop/đổi nhãn dataset ContactHands gốc. Có thể lưu derivative crop mới ở lượt sau, phải liên kết raw hash và bbox.

## 3. Ma trận tình huống cần quay/tiếp nhận

| Nhóm | Positive identity | Hard negative / đối chứng |
|---|---|---|
| Gap sau entry | Cùng tay đi từ ngoài vào, mất 1/nhiều frame rồi quay lại trong TTL | Tay cũ rời, tay khác vào gần bbox dự đoán |
| Occlusion | Cùng tay bị vật/người che rồi xuất hiện | Hai tay giao nhau/đổi thứ tự; hai người da/găng tương tự |
| Appearance | Cùng tay đổi hướng, lòng/bàn tay, ánh sáng, blur | Hai tay trái/phải cùng người; tay khác có nền/quần áo tương tự |
| Contact | Chạm rồi giữ yên sau tiếp cận, nhiều episode | Đi ngang không chạm, đứng gần tranh, tay ngoài ROI |
| Artwork | Tay thật trước tranh có hình bàn tay | Tay in sẵn, không có tay thật, reflection nếu có |
| Camera | Ổn định và giai đoạn phục hồi ổn định | Rung/pan, đổi góc, offline/reconnect |
| Scores/FPS | Contact score dao động trên cùng luồng, frame không đều | Low-score nhưng gần bbox, duplicate/stale/corrupt |

Mỗi nhóm cần nhiều phiên độc lập và cả positive/negative; thống kê số phiên, tay, gap, độ dài gap và điều kiện ảnh trước khi kết luận đủ dữ liệu. Không đặt số lượng ảnh bất kỳ làm chứng nhận đạt 80%.

Nhịp 1/5/10/15/30 FPS chỉ có thể đánh giá bằng downsampling video có mật độ thật đủ cao và timestamp thật. Không nhân bản/interpolate video 1 FPS thành 30 FPS để báo thử nghiệm. Không tăng tải ESP để ép 30 FPS. Khi thiếu nhịp, ghi NOT AVAILABLE.

## 4. Nhãn danh tính, bbox và occlusion

- hand_id là **một bàn tay vật lý trong một session**, không phải người, bbox index hay track ID AI. Hai tay cùng người có hai hand_id. Liên kết person_group_id dùng để quản lý split, không đưa vào matcher.
- Xem đủ đoạn trước/sau gap để xác nhận cùng tay; hai reviewer độc lập xem clip gốc. Nếu cần reference bổ sung/quan sát viên cho ground truth thì lưu provenance, không cấp reference cho thuật toán.
- Không phân biệt chắc chắn => identity_status=uncertain, hand_id=null. Không ép nhãn theo màu da, histogram, track ID hoặc kỳ vọng ALERT.
- entity_kind=depicted_hand dùng depiction_id của tác phẩm; không gán physical hand_id. entity_kind=uncertain khi không xác minh được thật/in.
- bbox dùng tọa độ **XYXY pixel liên tục, gốc 0**, x2>x1, y2>y1, nằm trong khung. Không trừ 1 như đọc VOC. Đây là schema mới, không sửa XML ContactHands.
- Bbox cho phần tay nhìn thấy; ghi partial/full/unknown occlusion. Full occlusion không bịa bbox, bbox=null. Không coi absence của detection là ground-truth full occlusion.
- Ghi frame/source/camera/clock, sai timestamp và camera stability GT riêng. GT stability chỉ dùng chấm điểm/chia nhóm, không cung cấp ngầm cho matcher khi đánh giá end-to-end.
- contact_events là nhãn riêng: contact/no_contact/uncertain theo video/quan sát, không lấy Object-Contact score hoặc ROI overlap làm sự thật vật lý. Nếu ảnh 2D không đủ => uncertain.

## 5. Gán nhãn cặp và gap

Chọn gallery observation **trước gap**, query observation sau gap; không dùng tương lai để lập gallery. Mỗi gap ghi continuity=same_hand/replacement/unknown/not_returned và bằng chứng reviewer. Cặp cùng hand_id không tự hợp lệ nếu nhãn chưa review hoặc timestamp không đủ.

Positive: cùng tay qua gap thật, không chỉ hai crop của cùng ảnh hay augmentation. Negative: khác tay có bbox/quỹ đạo/size gần giống, hai tay cùng người, thay thế trong cùng vị trí, tay thật so với tay in. Unknown: không thể theo dõi danh tính bằng mắt đáng tin cậy, giữ trong tập ambiguity; không bỏ âm thầm để cải thiện số liệu.

Không dùng only random easy negatives; báo phân bố negative và thực hiện hard-negative challenge riêng. Giới hạn số cặp gần trùng từ cùng gap để một phiên dài không lấn át các phiên khác.

## 6. Split chống rò rỉ

Dùng split=validation/test/unassigned; validation tương thích tên split Phase C. Toàn bộ session/capture_group và đoạn liên tục, bản sao, crop, gallery/query/pair thuộc cùng split. Không random từng ảnh/cặp. Khóa split/test manifest + hash trước chọn threshold.

Ưu tiên person_group_id, artwork/camera background được tách hoặc có holdout challenge riêng. Nếu người tham gia chưa ánh xạ đủ thì không tuyên bố person-disjoint. Báo kết quả theo seen/unseen person, background và điều kiện ánh sáng để phát hiện shortcut.

Threshold/feature/weight/min-crop/quality/gap/margin chỉ chọn trên validation. Test không dùng tune; không chọn camera-stability GT để làm input test. Với video có người trùng phiên, dùng capture_group chống lặp cả khi session_id khác.

## 7. Hoàn thiện biểu mẫu

Các CSV đi kèm chỉ có header; **không có mẫu dữ liệu giả**. JSON bundle theo annotation_bundle.schema.json là nguồn chuẩn; khi chuyển CSV, số/bool/null phải được chuyển kiểu rõ ràng (trống không có nghĩa 0). bbox/ROI và danh sách dùng JSON trong ô CSV có quote đúng. Annotation session cần approved status và hai reviewer trước đánh giá chính thức.

Trước chạy evaluator tương lai phải kiểm tra: hash/file tồn tại, reference ID duy nhất và khớp, positive-area bbox/bounds, timeline/clock, ROI version/hình học, nhãn đủ review, group/split không rò rỉ, pair có trước-sau và evidence. JSON Schema không thực hiện các ràng buộc chéo này; chưa có semantic validator được triển khai trong lượt này.

## 8. Dừng và tiêu chí sẵn sàng

Chưa có phiên đủ nhãn => không có appearance benchmark, không tính Accuracy/Precision/Recall/F1. Sau khi duyệt schema và có ít nhất một bộ raw có timestamp + nhãn review bao phủ positive/hard-negative, mới đề xuất triển khai validator/extractor CPU ở thư mục thử nghiệm mới. Chưa tự chạy camera hoặc GPU.
