# Chuẩn bị đánh giá AI với annotation v2 — chưa chạy mô hình

## 1. Điều kiện trước đánh giá

Chưa có video thật đã review theo camera mép trên. Bộ fixtures SYNTHETIC_TEST chỉ kiểm tra hợp đồng, không phải prediction/AI benchmark. Không tính Accuracy hay Precision/Recall từ unit test annotation.

Cần có: media thật/raw không overlay và hash; provenance đúng camera; session/video/frame/clock refs; ROI/calibration/coverage đã review; ground truth độc lập và sync/error; các đoạn TOUCH/NEAR_NO_TOUCH/NO_TOUCH/UNKNOWN; split theo phiên/nhóm nguồn; prediction thật đóng băng và code/config hashes. Tất cả tham số chỉ chỉnh trên validation, khóa trước test.

Annotation hợp lệ hoặc REAL_CAPTURE marker không đủ chứng minh readiness. --require-real chỉ từ chối marker test; --asset-root chỉ kiểm tra tồn tại/hash, không xác minh GT. Cần review nội dung, chất lượng nhãn và độ phủ. Không biến synthetic fixtures thành REAL_CAPTURE.

## 2. Định nghĩa scope và UNKNOWN

Phân biệt:
1. GT UNKNOWN: sự thật vật lý chưa xác minh được.
2. Prediction UNKNOWN/UNCERTAIN: hệ thống từ chối quyết định.
3. Camera OFFLINE/MOVING: tình trạng nguồn, không phải NO_TOUCH.
4. Không thấy tay: output detection, không chứng minh không có touch ngoài FOV.

Báo tổng số/thời lượng tất cả mẫu, phần có GT rõ, GT UNKNOWN, prediction UNKNOWN, offline/moving và ngoài vùng quan sát. Không loại các nhóm này khỏi toàn bộ báo cáo.

Accuracy trên GT rõ = số dự đoán đúng nhãn vật lý / tất cả window có GT rõ. Prediction UNKNOWN trên GT rõ vẫn nằm trong mẫu số, không được tính đúng. Bên cạnh đó báo correct_on_known / total_windows dưới tên conservative all-window correct rate (không gọi là physical Accuracy), GT-known coverage và abstention. Không tuyên bố accuracy toàn hệ thống nếu phần GT chưa rõ/ngoài FOV chưa được giải quyết.

GT UNKNOWN không được ép thành negative để tạo TN. Báo ma trận đầy đủ gồm hàng GT UNKNOWN; chỉ chấm metric vật lý khi có căn cứ, công bố mẫu số cụ thể. Selective accuracy trên phần hệ thống quyết định phải kèm coverage, không thay thế số liệu chính.

## 3. Classification và confusion matrix

Khóa trước độ dài/window stride và quy tắc gán nhãn window chứa biên/chạm rất ngắn. Không tự chọn window sau xem test. Báo riêng near_no_touch và no_hand để tránh nhiều negative dễ lấn át ca khó.

Ma trận: hàng GT TOUCH/NEAR_NO_TOUCH/NO_TOUCH/UNKNOWN; cột prediction TOUCH/NEAR_NO_TOUCH/NO_TOUCH/UNKNOWN. Pipeline hiện chưa có classifier bốn nhãn này; mọi mapping từ ALERT/CANDIDATE phải được định nghĩa và duyệt trước, không mặc định ALERT=TOUCH được xác minh.

Precision_class=TP/(TP+FP); Recall_class=TP/(TP+FN); F1=2PR/(P+R). Prediction UNKNOWN trên true TOUCH tạo missed decision/FN trong operational recall. Báo macro metrics và số lượng mỗi lớp; mẫu số 0 => N/A, không đặt 1 để báo đẹp.

Accuracy >80% và Precision/Recall/F1 >=80% chỉ được kết luận từ test độc lập đã khóa, cùng độ phủ và uncertainty. Nêu CI theo phiên khi đủ dữ liệu, không coi cặp/frame gần trùng là mẫu độc lập. Pilot 12 phiên chưa bảo đảm đủ bằng chứng.

## 4. ALERT/event và thời gian

Giữ riêng đánh giá risk ALERT và xác minh contact vật lý. So cùng frozen prediction/timestamps/ROI/score threshold/timeout/stability stream cho D/E, F strict, F geometry opt-in offline và appearance khi được duyệt sau này. Không bật F geometry mặc định.

Match một alert với tối đa một contact episode, trong dung sai thời gian khóa từ validation và có xét sai số annotation/sync. Unmatched alert -> FP; contact không có alert -> FN; đếm duplicate alert riêng. Window confusion và event matching có mẫu số khác nhau; event không tự sinh TN.

False alerts/hour = unmatched alerts / giờ no-contact đã gán nhãn, trong phạm vi theo dõi được. Không cộng offline/GT UNKNOWN vào giờ no-contact sạch. Báo cả thời lượng bị loại và downtime, không che vùng mù.

Alert latency: contact onset -> alert đầu tiên trên clock đồng bộ; báo median/p95, boundary/sync uncertainty và số miss. Nếu capture timestamp thiếu hoặc alignment chưa đủ thì end-to-end latency NOT MEASURABLE; chỉ báo host_receive-to-alert nếu đo được, với tên đúng. Event không có thời gian rõ vẫn lưu annotation nhưng không bịa delay.

## 5. Coverage và phân tầng

Báo:
- FOV coverage: visible surface fraction nếu đo được; UNKNOWN nếu chưa đo.
- Observable coverage: phần đủ rõ để đánh giá, riêng vùng gần/giữa/xa.
- Temporal availability: thời gian frame/nguồn dùng được / thời gian dự kiến.
- Decision coverage: số mẫu có quyết định / số mẫu được quan sát.
- GT UNKNOWN rate và prediction UNKNOWN rate với mẫu số nêu rõ.

Không dùng frame thấy được để tuyên bố bảo vệ toàn bộ tranh. Nếu GT tham chiếu xác nhận touch ngoài FOV, báo missed protection/outside-coverage riêng trong kết quả dịch vụ; không lặng lẽ bỏ khỏi mục tiêu toàn tranh.

Báo theo người/phiên, ánh sáng/bóng, tốc độ, kích thước tay, occlusion, gap, stability và tay in. Tính false handoff, ID switch, recovery recall/coverage ở nhánh Re-ID riêng; không suy từ số ALERT thấp.

## 6. Những gì chưa có

Không có evaluator AI/scorer mới trong bộ này; chỉ chuẩn bị schema/field/quy ước để triển khai sau phê duyệt. Chưa có runtime ROI converter, stability extractor đã xác minh, crop/feature/appearance recovery hoặc prediction GPU mới. Cần kiểm tra semantic liên-bundle, duplicate/person leakage và độ đầy đủ nhãn trước đánh giá.

Các ngưỡng ContactHands hiện tại và mọi quality gate FAIL cũ được giữ nguyên. Các metric AI thực tế: **CHƯA ĐÁNH GIÁ**.
