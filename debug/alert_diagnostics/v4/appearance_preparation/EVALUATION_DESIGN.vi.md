# Thiết kế đánh giá appearance-assisted recovery — chưa triển khai

## 1. Câu hỏi và giới hạn

Appearance có giúp phân biệt cùng tay sau mất dấu với tay khác thay thế khi hình học tương tự không? Cần giảm chuyển nhầm ROI entry/history mà vẫn đo các trường hợp bỏ lỡ tiếp xúc thật. Ít ALERT hơn không chứng minh tốt hơn.

Bbox/score/timestamp giống nhau không chứng minh cùng danh tính (xem phase_f/identity_observability.json). Đặc trưng ảnh cũng không bảo đảm nhận dạng: tay nhỏ/mờ, găng giống nhau, lòng/bàn tay khác góc, background/overlay giống có thể làm sai. Chưa có dữ liệu để tuyên bố phương án hoạt động.

## 2. Baseline appearance đơn giản đề xuất

Ở lượt sau, chỉ sau phê duyệt và có dữ liệu:

1. Lấy crop từ **raw frame chưa overlay** bằng bbox prediction, clip đúng ảnh. Chất lượng thấp, bbox rỗng, quá nhỏ, che nhiều hoặc timestamp không hợp lệ => không có cue tin cậy.
2. Chuẩn hóa aspect ratio bằng resize + padding có mask; histogram không tính padding. Giữ thiết kế foreground/background rõ ràng; bbox rộng có thể so khớp nền tranh. Không xóa nền bằng nhãn oracle.
3. Feature CPU: histogram HSV chuẩn hóa kết hợp histogram gradient/HOG-style đơn giản. Có thể dùng Pillow/NumPy sẵn có; chưa chọn bin, resize, trọng số hay threshold tối ưu. Không tải weights hoặc train embedding.
4. So độ giống histogram và cosine gradient, kiểm tra chất lượng crop. Ablation color-only / gradient-only / kết hợp, thêm geometry-only. Không dùng hash ảnh làm identity.
5. Gallery gồm một số quan sát chất lượng tốt **trước gap**, lưu thời gian/nguồn. Chỉ update sau association đã xác nhận; freeze khi uncertain để tránh gallery poisoning. Không lấy ảnh tương lai của query.
6. Mọi crop/feature tương lai phải có raw hash, bbox, feature version, clock, tham số. Chưa tạo crop/features ở lượt này.

Nguồn 320×240 và ảnh evidence mờ/overlay hiện có là rủi ro lớn; không hứa CPU baseline đủ phân biệt hai tay gần giống.

## 3. Hợp đồng recovery bảo thủ

Provider đề xuất trả SAME / DIFFERENT / **UNCERTAIN**, cùng score, quality, top1/top2 margin, candidate IDs, feature version và lý do. Score không gọi là probability nếu chưa calibration.

Chỉ đề xuất cùng tay khi đồng thời:
- timestamp mới/tăng dần, nguồn và clock hợp lệ, không duplicate/stale;
- gap còn trong timeout/recovery window đã cấu hình, không kéo dài TTL bằng probation;
- camera stability đáng tin là STABLE; UNKNOWN/MOVING không tương đương STABLE;
- geometry/size/motion còn khả thi và assignment một-một;
- appearance đủ chất lượng, similarity và margin qua threshold đã khóa trên validation;
- bằng chứng mới nhất quán qua các quan sát độc lập, không chỉ một crop mờ.

Candidate hòa điểm, chỉ có một candidate nhưng thiếu cue, identity khó phân biệt, pose đổi mạnh, ảnh không có/overlay => UNCERTAIN. Không fallback sang geometry dễ dãi để ép recovery. Không dùng ground-truth hand_id/person_group/continuity/contact/camera stability làm feature.

SAME chỉ mở khả năng khôi phục liên kết/entry episode sau kiểm tra an toàn; **không sao chép vote/history contact trước gap** để kích hoạt ngay. Phải đủ bằng chứng contact mới theo Phase D và giữ ngưỡng ContactHands hiện tại. Mất detection, offline, corrupt và stale không phải contact. Không đủ freshness => bỏ entry, xác nhận lại. Tay giữ yên sau entry hợp lệ vẫn có thể xác nhận; chuyển động không phải điều kiện vĩnh viễn.

Đây là hợp đồng đề xuất cho adapter tương lai, chưa thay Phase F. Geometry opt-in vẫn OFF mặc định; không sửa FAIL cũ.

## 4. Hai tầng đánh giá độc lập

**Tầng A — diagnostic appearance:** bbox GT đã review để nghiên cứu ảnh/cặp. Kết quả chỉ là pair retrieval/matching; không đại diện pipeline phát hiện tay hoặc ALERT.

**Tầng B — end-to-end offline:** cùng frozen prediction ContactHands thật, raw frame, timestamp, source/ROI/stability signal cho D/E/F/appearance. Crop bằng bbox prediction; GT bbox chỉ để chấm match, không cấp cho matcher. Missed detection là lỗi upstream phải tính vào contact recall; không loại bỏ để làm đẹp kết quả.

Nếu stability được mô phỏng/đánh dấu oracle thì ghi rõ controlled diagnostic, không gọi end-to-end thực tế. Hiện chưa có stability provider được xác minh qua video. ROI/clock đổi phải tạo barrier theo logic bảo vệ, không suy camera ổn định từ bbox.

## 5. Ma trận so sánh tái lập

| Variant | Vai trò | Ghi chú |
|---|---|---|
| D/E | Baseline logic/adapter | D nhận cùng geometry từ export; E nhận prediction wrapper tương đương |
| F strict | Bảo thủ mặc định | Thiếu bằng chứng danh tính thì không chuyển entry |
| F geometry | Đối chứng offline opt-in | Có rủi ro FP đã biết; không bật mặc định |
| Appearance-assisted | Đề xuất, chưa code/chưa chạy | Phải có cue; UNCERTAIN không inheritance |

Tất cả dùng cùng session split, prediction JSONL/hash, raw hashes, ROI version, score threshold, camera-stability stream, source timestamp, cooldown và timeout. Báo timeout 1/2/3 riêng, không mặc định 3 tốt nhất; F hiện còn cap recovery window 1.5 giây (recovery_tracker.py:14). Không chỉ đổi max_idle để che sự khác nhau. Lưu effective config từng variant và time budget.

Với D/E không có appearance, chúng vẫn nhận đúng cùng detections/time; chỉ adapter đổi representation, không sửa prediction. Mỗi run phải lưu code hash, manifest/label/config hashes, feature version/parameters, split, frame reject reason, candidate scores/margins, decision, inheritance, ID mapping GT ở scorer riêng, event và contact evidence mới.

Không chạy các runner cũ vì chúng có thể ghi artifacts vào Phase C/F. Adapter/scorer mới phải ở thư mục mới được phê duyệt; output exclusive. Chưa cung cấp lệnh chạy evaluator không tồn tại.

## 6. Positive, negative và ambiguity

- Positive cùng tay qua mất dấu/occlusion, đổi tốc độ/hướng, các góc tay, ánh sáng; giữ nhãn ground truth độc lập đặc trưng.
- Negative khó: hai tay cùng người hoặc khác người gần giống; bbox/quỹ đạo tương tự; tay cũ đi khỏi, tay mới đến gần dự đoán; thật/in cùng vị trí; găng/nền giống nhau.
- Unknown truth là nhóm riêng, không cưỡng ép same/different và không đánh giá như negative dễ.
- Tập pair cân bằng không phản ánh prevalence triển khai; báo pair benchmark và video natural prevalence riêng.
- Gallery/query không vượt split hoặc dùng tương lai. Không dùng cùng ảnh/augmentation làm bằng chứng recovery thực.

## 7. Chỉ số cần báo

### Identity/recovery
Trên nhãn same/different đã review: confusion matrix có cột dự đoán SAME/DIFFERENT/UNCERTAIN. Báo precision của SAME, recall phục hồi đúng, false handoff rate trên negative, số correct/wrong recovery, ID switches, gallery contamination, coverage/abstention.

UNCERTAIN trên positive là **missed recovery trong operational recall**, không bỏ khỏi mẫu số. Báo selective accuracy trên phần được quyết định kèm coverage, không gọi là accuracy chung. Với truth unknown: chỉ báo quyết định/abstention và audit nguy cơ, không bịa TP/TN.

### Contact/ALERT
Dùng contact GT độc lập; match event một-một trong cửa sổ thời gian đã khóa trên validation. Định nghĩa rõ contact episode, duplicate alert và unmatched event. Báo TP/FP/FN, precision=TP/(TP+FP), recall=TP/(TP+FN), F1; mẫu số 0 => N/A.

Accuracy=(TP+TN)/tổng chỉ hợp lệ trên **cửa sổ thời gian có nhãn** với quy tắc window/overlap cố định; event không tự sinh TN. Báo confusion matrix window riêng và tránh chi phối bởi nhiều giờ no-hand. False alarms/hour = số alert không match chia số giờ no-contact được gán nhãn; không dùng thời gian offline/unknown làm giờ quan sát sạch.

Delay từ contact onset đến ALERT đầu tiên cho các event match, báo median/p95 và số event miss. Delay inference/processing/capture-to-alert khác nhau; không có đồng bộ clock thì không gọi là end-to-end latency. Over-recovery có thể tăng recall nhưng thêm FP; conservative rejection có thể mất alert thật: báo cả hai.

Báo theo session, scenario, gap/FPS, kích thước/occlusion/stability; uncertainty/CI theo session khi đủ mẫu, không coi hàng ngàn cặp gần trùng là độc lập. Chọn tất cả threshold trên validation, khóa rồi mới test.

## 8. Rủi ro và điều kiện quyết định

FP: background/overlay shortcut, hai tay/găng tương tự, gallery bị đầu độc, camera pan, bbox prediction lấy phần tranh. FN: tay nhỏ/mờ, đổi lòng/bàn tay, TTL ngắn, dropout dài, stability UNKNOWN, abstention nhiều. Ảnh 2D không chứng minh tiếp xúc vật lý; appearance chỉ hỗ trợ identity, không sửa ContactHands.

Nếu same và replacement không phân biệt đáng tin, giữ UNCERTAIN và ghi missed contact có thể xảy ra; không truyền entry/history. Chưa thể định lượng đánh đổi Precision/Recall hoặc đặt similarity threshold.

**Accuracy >80%, Precision/Recall/F1 ≥80%: CHƯA ĐÁNH GIÁ.** Unit test B–F, audit file và cặp giả lập không được dùng làm độ chính xác nhận diện ảnh thật.
