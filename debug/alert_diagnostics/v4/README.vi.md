# ArtGuard v4 — bản thử nghiệm logic độc lập

Trạng thái: Giai đoạn B hoàn thành. Chỉ logic/replay; không inference GPU hoặc camera.
Accuracy, Precision, Recall, F1 và chất lượng trên video thật: CHƯA ĐÁNH GIÁ.

## Phạm vi và bảo vệ

Mọi mã/output mới nằm dưới debug/alert_diagnostics/v4/.
Worker v3, contact_logic.py, checkpoint, dataset, database, môi trường và ứng dụng web giữ nguyên.
Không có client SQL Server, camera, import torch/cv2/Detectron2 hoặc cài dependency trong các module v4.
File output được tạo độc quyền (x), mỗi lần chạy có thư mục mới. Không commit/push.
build_inputs/ giữ source payload đã compile/test trong RAM trước khi tạo module cuối, tránh ghi đè.
protected_before.json và protected_verification.json chứa đối chiếu file gốc.

## File và trách nhiệm

- tracking_v4.py: ghép tối ưu tổng chi phí, dự đoán vị trí theo dt, gate bảo thủ khi nối lại,
  từ chối ghép mơ hồ, ID duy nhất và giới hạn số track.
- roi_entry_v4.py: quỹ đạo ngoài→trong, overlap hysteresis, entry theo episode.
- temporal_v4.py: bằng chứng có timestamp, hỗ trợ thời gian, event lifecycle.
- pipeline_v4.py: schema, chuẩn hóa input, timestamp/dedupe/stale gate, camera disconnect.
- scenarios.py: đầu vào bbox/score kiểm soát; không phải dữ liệu model hoặc dataset.
- compare_v3_v4.py: replay cùng input cho các hàm v3 nguyên bản và v4.
- test_comparison.py: 40 test logic và an toàn.
- run_tests.py: chạy test, tạo trace và báo cáo mới.
- run_v4.py: CLI replay prediction JSONL, không inference ảnh.
- config.v4.json: config riêng, ROI thử chưa hiệu chuẩn, timeout tham chiếu 2s.
- __init__.py: khai báo package, không khởi chạy chức năng.
- preflight_01.json: kết quả 40/40 khi compile source trong RAM.
- RESULTS.vi.md: kết quả thực tế và giới hạn.

## Hợp đồng input

BBox chuẩn hóa 0..1. Ví dụ một dòng JSONL:

```json
{"frame_id":"camera-session-001:12","timestamp":2.4,"received_timestamp":2.5,"detections":[{"box":[0.4,0.3,0.5,0.5],"hand_score":0.99,"object_contact_score":0.6}]}
```

Timestamp là giây trong cùng một source clock, tăng nghiêm ngặt. Replay video dùng timestamp video.
received_timestamp phải cùng clock và không trước timestamp; nếu không cung cấp,
pipeline chỉ kiểm tra thứ tự/dedupe, không thể biết tuổi frame thực tế.
Không trộn time.monotonic của hai tiến trình hoặc mtime epoch với clock video.
File mtime không phải thời điểm camera phơi sáng.
Từ chối frame trùng ID, timestamp bằng/đảo chiều, frame quá cũ (>3s nếu có receive time).
Frame bị từ chối không cập nhật track, ID, entry hoặc bằng chứng.
Cache ID đầy (4096 frame) thì dừng nhận mẫu thay vì quên ID và nhận lại frame trùng.
Đây là giới hạn bản replay có thời lượng hữu hạn, cần session mới cho phiên dài hơn.

Tất cả input detection được kiểm tra trước khi cập nhật state. Bbox ngoài biên được clip;
bbox đảo/rỗng hoặc score NaN/out-of-range bị từ chối. Hand score dưới 0.7 không tạo bằng chứng.
Label trong controlled_inputs chỉ phục vụ kiểm thử, không dùng để ghép track.
Không loại quan sát mới chỉ vì ảnh/score giống nhau: tay thật giữ yên vẫn cần được xác nhận.

## Tracking và entry

Timeout giữ ID độc lập với lịch sử chạm. Thử timeout 1/2/3s, không coi 2s hoặc 3s là tối ưu.
Dự đoán vị trí có giới hạn horizon/velocity; không dự đoán ra bằng chứng tiếp xúc.
Ghép mơ hồ không truyền entry/history sang detection khác; điều này có thể tăng ID mới/false negative.
Một track mất detection vẫn có thể giữ ID, nhưng lịch sử xác nhận bị xóa.
Khi camera disconnect, tất cả track và bằng chứng bị xóa; ID không được dùng lại.

Entry cần ngoài rõ ràng (overlap <=0.2 và tâm ngoài ROI), rồi trong rõ ràng (overlap >=0.4),
với tổng dịch chuyển >=0.015. Không yêu cầu mỗi bước vượt biên lớn.
Bằng chứng ngoài có hạn 10s. Exit ngoài liên tục >=0.4s re-arm episode tiếp theo.
ROI rectangle/polygon dùng geometry có sẵn. Khi đổi ROI, tạo PipelineV4 mới,
không gán ROI mới vào pipeline đang có state.
Tay sinh sẵn trong ROI không tự có entry; OC cao không chứng minh là tay thật.

## Temporal

Ngưỡng ContactHands bị khóa tại hand=0.7, OC=0.15, fast=0.85, overlap=0.30.
Config không được hạ hoặc đổi các ngưỡng này trong giai đoạn này.
Bằng chứng chỉ được tích lũy sau entry. Frame xác nhận phải hợp lệ ngay lúc phát event.
Window tối đa 5 mẫu, ít nhất 3 dương; mẫu quá 6s bị loại.
Nhánh window cần hỗ trợ >=0.4s từ các cặp mẫu dương liền kề:
mỗi khoảng đóng góp tối đa 0.5s, không nối qua khoảng >2s hoặc detection miss.
Đây là hỗ trợ quan sát, KHÔNG phải thời gian tiếp xúc vật lý đã chứng minh.
Fast path cần >=2 mẫu >=0.85 và span >=0.2s, không dùng frame trùng.
EMA chỉ telemetry, không biến raw score thấp thành frame dương.
Gap >2s ngắt lịch sử kể cả ID còn sống. Missing không tăng positive_frames hoặc support_seconds.
Khi đã ALERT, đứng yên không làm mất cảnh báo. Mất detection ngắn giữ episode theo grace 2s,
hiển thị observed=false và không phát event mới. Observed low-score dùng clear_after=0.75s.
Mỗi track/entry episode chỉ phát một event; event_key chỉ duy nhất trong run,
khi tích hợp ngoài cần thêm run/session ID.
Sau clear/cooldown, cùng episode được khôi phục mà không phát event trùng;
confirmed exit + entry mới mới đủ điều kiện episode mới.
Cooldown mặc định vẫn 60s; test re-entry dùng cooldown ngắn tường minh chỉ để kiểm tra lifecycle.

## Chạy logic

```bash
cd /mnt/c/Users/LEGION/Pbl4
/home/legion/miniconda3/envs/contacthands/bin/python -B -m debug.alert_diagnostics.v4.run_tests
```

Không cần activate CUDA cho test. Outputs mới dưới v4/runs/logic_v4_<UTC>_<random>/.
comparison.jsonl lưu input và v3/v4 từng frame; comparison_summary.json tổng hợp 13×3 trường hợp.
controlled_inputs.jsonl có thể replay độc lập. Không cộng số test preflight và test file thành 80 test khác nhau.

## Lệnh replay đã kiểm tra

```bash
cd /mnt/c/Users/LEGION/Pbl4
/home/legion/miniconda3/envs/contacthands/bin/python -B -m debug.alert_diagnostics.v4.run_v4 \
  --input debug/alert_diagnostics/v4/runs/logic_v4_20261017T034029080685Z_ecbd455a/controlled_inputs.jsonl \
  --scenario slow_entry --track-timeout 2
```

Dùng cùng lệnh với timeout 1/3 để so sánh. Mỗi run output mới, không ghi database.
Với prediction JSONL thật đã có và được phê duyệt, thay --input và bỏ --scenario nếu không có nhiều cảnh.
Runner này KHÔNG nhận JPEG/video hoặc khởi chạy AI; adapter inference thật thuộc bước được duyệt riêng.

## Đánh giá sau này

Cần benchmark thu prediction/timestamp thật rồi replay cùng dữ liệu cho hai phiên bản.
Đo decode, chuyển tensor, hai stream model, tracking, encode và I/O riêng; báo cáo warm-up, p50/p95/p99.
Đối chiếu video có nhãn vật lý theo phiên quay độc lập; chốt quy tắc TP/FP/FN và matching event trước.
Tinh chỉnh trên validation, khóa tham số trước test; không dùng test chọn timeout.
Camera dịch chuyển, che khuất nhiều tay và OC sai cao kéo dài vẫn khó.
Score oscillation bị chặn có thể giảm cả false positive lẫn recall; cần nhãn thật để phân biệt.
Accuracy >80% và Precision/Recall/F1 >=80% là mục tiêu chưa được đo, không phải kết quả unit test.
