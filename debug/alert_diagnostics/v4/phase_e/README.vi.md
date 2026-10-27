# Phase E — pipeline ContactHands offline

## Phạm vi

Mã thử nghiệm riêng. Không thay v3/v4/C/D, cấu hình sản phẩm, checkpoint, dataset, DB, web hoặc môi trường. Không có inference/camera worker. ALERT chỉ là event JSONL, chưa lưu SQL Server hay ảnh evidence.

Luồng: ContactHands export JSONL -> prediction_adapter -> stability provider -> PipelineD -> tracking/ROI entry/temporal -> frames.jsonl + summary.json.

Tái sử dụng trực tiếp `PipelineD`; không viết lại thuật toán cảnh báo. Adapter phụ thuộc cả `_gate` và `_clear_state` nội bộ của D để kiểm tra freshness trước decoding và ngắt bằng chứng khi payload hỏng. Đây là API nội bộ thử nghiệm, được khóa bằng hash và regression test, cần chuẩn hóa public API ở giai đoạn sau.

## Lệnh đã chạy được trên WSL, Python 3.7.16

### Kiểm toán logic đầy đủ, có guard

```bash
cd /mnt/c/Users/LEGION/Pbl4
/home/legion/miniconda3/envs/contacthands/bin/python -B -m debug.alert_diagnostics.v4.phase_e.runtime_audit
```

Hiện **exit 1**: E còn hai quality gates phục hồi FAIL; không đổi expectedFailure/skip để làm xanh. B/C giữ nguyên năm FAIL đã biết, D 64/64 PASS. Xem RESULTS.vi.md.

`run_tests.py` lưu inventory module tên forbidden_runtime_modules_loaded theo chính sách quá nghiêm: sqlite3 được import gián tiếp bởi baseline v3. Import không mở database. `runtime_audit.py` là entry kiểm toán ưu tiên: patch chặn sqlite3.connect/dbapi2.connect, network connect, xóa/đổi tên và mọi ghi ngoài E; lần chạy thực tế 0 thao tác bị cấm được gọi. Inventory sqlite3 không phải bằng chứng DB đã bị truy cập. Mọi kết quả runner đầu tiên vẫn được giữ nguyên.

### Demo JSONL rectangle

```bash
/home/legion/miniconda3/envs/contacthands/bin/python -B -m debug.alert_diagnostics.v4.phase_e.replay \
  --input debug/alert_diagnostics/v4/phase_e/fixtures/slow_entry.jsonl \
  --config debug/alert_diagnostics/v4/phase_e/fixtures/slow_entry.settings.json \
  --simulate-stability
```

Đã chạy: exit 0, 15 frame, 1 event. Cờ simulate-stability **chỉ dành cho prediction/tín hiệu kiểm soát**, không dùng làm xác minh nền ảnh thật.

Đổi tên slow_entry thành polygon_slow_entry ở hai đường dẫn để chạy polygon: đã chạy exit 0, 1 event.

Bỏ --simulate-stability trên cùng fixture: đã chạy exit 0, 0 event, 15/15 record decision_available=false. Exit 0 CLI chỉ cho biết input không bị reject; không có nghĩa camera đủ điều kiện giám sát.

Mỗi lần tạo `runs/offline_<UTC>_<UUID>/` mới. Output parent phải nằm trong E; không ghi đè output cũ. CLI exit 1 khi có record bị reject. Không có tự động mở model/camera/DB.

## Schema config

Chỉ schema_version=1 và sources. Mỗi nguồn có session_id, calibration_id và pipeline_config; nguồn/session dùng A-Z, a-z, 0-9, dấu chấm/gạch dưới/gạch ngang, dài 1..64.

ROI phải khai báo rõ enabled=true, normalized=true và shape. Rectangle có coordinates=[x1,y1,x2,y2]; polygon có points=[[x,y],...], được D/geometry kiểm tra. Đây là ROI fixture, không phải ROI đã hiệu chuẩn tranh thật.

Không tự thay vùng tranh bằng toàn bộ ảnh, không tự lấy ROI mặc định của D nếu config thiếu ROI. Không cho record prediction tự đổi ROI; tạo phiên cấu hình/calibration mới khi cần thay đổi.

Các ngưỡng D giữ nguyên: hand 0.7, Object-Contact 0.15, fast 0.85, overlap 0.3. Timeout/trạng thái temporal dùng D, không nới ngưỡng để ép ALERT.

## Schema JSONL

Một JSON object mỗi dòng, schema_version=1. Prediction:

```json
{"schema_version":1,"kind":"prediction","source_id":"painting0","session_id":"boot0","frame_id":"42","timestamp":1.4,"received_timestamp":1.5,"image_size":[480,640],"coordinate_space":"pixels_xyxy","prediction":{"pred_boxes":[[100,120,180,220]],"scores":[0.99],"pred_cats":[[0.3,0.4,0.2,0.8]]}}
```

- image_size=[height,width], dương và nguyên; bbox XYXY liên tục. pixels_xyxy chia x cho width, y cho height; normalized_xyxy không chia thêm. **Không trừ 1 theo VOC.**
- Arrays phải cùng số hàng, <=32 detections. Bbox rỗng/đảo, NaN/Inf/bool/string số, score ngoài [0,1] bị reject.
- pred_cats có đúng bốn sigmoid độc lập theo thứ tự No-Contact, Self-Contact, Other-Person-Contact, Object-Contact. Lấy cột 3, không argmax/softmax/chuẩn hóa tổng.
- D làm clipping bbox và lọc hand score. Conversion log ghi tọa độ gốc/chuẩn hóa, score từng lớp và clipping dự kiến.
- Timestamp là giây trên cùng clock của nguồn/session, tăng nghiêm ngặt; received_timestamp cùng clock, không sớm hơn capture. Bắt buộc có receive time, không tự coi frame là mới khi thiếu.
- Freshness dùng dữ liệu receive time đã ghi, không so timestamp replay với đồng hồ hiện tại. Độ tin cậy metadata phải được đảm bảo ở exporter thật.
- Mỗi source được cấu hình trước, có PipelineD/cache/ID/history/session riêng. Event key bổ sung source_event_key để tránh trùng giữa các nguồn.
- oracle chỉ là metadata test, matcher không dùng nhãn actor. Không dùng fixture làm dataset hoặc dữ liệu benchmark AI.

Các kind còn lại:

| kind | Ý nghĩa |
|---|---|
| prediction với ba arrays rỗng | Frame ảnh hợp lệ, không có detection; có thể NO_HAND nếu stability đủ |
| missing | Có mốc thời gian frame bị mất, không có prediction; input cho D là observation rỗng |
| frame_error | Frame không đọc/giải mã được, không có prediction; không cộng bằng chứng |
| disconnect | Control riêng; xóa active/history/entry, CAMERA_OFFLINE, đi trước cache/dedup/timestamp gate |
| reconnect | Control rõ ràng; previous_session_id phải khớp, session_id mới, calibration_id hợp lệ; cần entry mới |

Missing/error cần frame_id, timestamp, received_timestamp. Không cho vừa missing vừa có prediction. Không tự suy ra một frame mất là một frame tiếp xúc. Disconnect có thể bỏ timestamp/ID, vẫn xử lý an toàn. Không tự reconnect từ prediction.

Resolution đổi bị reject và xóa trạng thái; cần reconnect/calibration rõ ràng. ROI normalized không có nghĩa thay resolution/camera pose luôn an toàn.

## Frame mới, trùng và payload lỗi

- Duplicate, non-increasing timestamp, stale (>3 giây), cache đầy: không cộng hoặc xóa lịch sử chỉ vì frame cũ bị phát lại.
- Payload hỏng tại frame mới: INPUT_ERROR, xóa state qua D barrier, không tạo timestamp/detection giả. Giữ ID counter và last_timestamp; tay xuất hiện lại bên trong không tự thừa hưởng entry.
- JSON lỗi/duplicate key/NaN constant/UTF-8 lỗi/record quá 256 KiB: log rejection. Khi không xác định được nguồn do JSON hỏng, xóa trạng thái tất cả nguồn; lựa chọn bảo thủ có thể làm giảm Recall nguồn khác.
- Không có watchdog timer/capture loop. Producer tương lai phải gửi missing/disconnect khi biết mất frame/kết nối.
- D có thể giữ alert_active trong missing_grace như telemetry lịch sử. Top-level missing/error trả decision_available=false và current_image_available=false; không hiển thị như camera đang giám sát hợp lệ.

## Stability interface

`StabilityProvider.assess(frame_id,timestamp,session,context)` trả status STABLE/MOVING/UNKNOWN, stable boolean và reason. reference_id được cập nhật qua D reconnect.

- Mặc định: UNKNOWN, không tạo entry/evidence.
- SimulatedStability: chỉ bật rõ ràng bằng flag offline; signal phải khớp source_id/session_id/frame_id/timestamp/reference_id. Không cache STABLE sang frame kế tiếp.
- MOVING hoặc UNKNOWN gọi chính sách clear của D, active không tiếp tục như camera ổn định.
- CorrespondenceStability là API opt-in tương lai, gọi validator D, chưa có extractor và không bật qua CLI hiện tại. Context kiểu D cần provider=background_correspondences, source_id, source_session, frame_id, timestamp, reference_id, matches. Chưa có bằng chứng ảnh thật.

Đề xuất bước ảnh thật sau (chưa triển khai/chưa xác minh): features trên mask nền ngoài ROI/hand/foreground; forward-backward optical flow; robust affine/homography; kiểm tra phủ không gian, inlier và reprojection so mốc hiệu chuẩn cố định. Thiếu texture, rung/mờ, parallax, rolling shutter => UNKNOWN. Không suy camera ổn định từ bbox tay hoặc cờ trong JSONL thực tế.

## Log và so sánh

frames.jsonl ghi line number/hash input, source/session/frame/time, trạng thái và reason, used_for_confirmation, score/bbox conversion, track ID/entry episode/votes/support/state_reason, event và pipeline_result nguyên bản của D.

used_for_confirmation chỉ nói quan sát hợp lệ trong ROI đã đi qua entry được gửi vào D; không chứng minh tiếp xúc vật lý, không đảm bảo sẽ sinh event mới.

offline_comparison.json chứa 31 kịch bản/809 record. 808 record so sánh core trực tiếp D, 0 khác biệt; 1 payload hỏng không thể đưa thẳng vào D, adapter ngắt bằng chứng và log rõ. Metadata provider khác nhau nên so core accepted/state/tracks/events, không giả vờ log toàn bộ giống nhau.

Replay qua file thật và gọi process in-memory cũng được đối chiếu. Lưu input SHA-256, config, full log và summary để tái lập.

## Kết nối ContactHands thật ở lượt sau

Serializer CPU duck-typed đã có test, không import Torch. Liên kết source:
- src/realtime_worker_integrated_v3.py:28-35 lấy pred_boxes.tensor/scores/pred_cats.
- src/core/contact_logic.py:5 xác định thứ tự contact.
- src/contact_hands_two_stream/modeling/roi_heads/contact_head.py:77 tạo sigmoid.

Exporter tương lai nhận Instances đã chuyển CPU từ bước inference được phê duyệt, dùng serialize_instances(), image_size và metadata capture; xuất JSONL trước ROI filtering. Serializer từ chối tensor GPU, không tự gọi model hay chuyển device. Cần thêm nguồn stability ảnh thật đã thẩm định trước giám sát; không dùng simulate-stability cho deployment.

## Đánh giá và giới hạn

Unit/contract, integration offline và đánh giá model là ba loại khác nhau. Hai quality gate phục hồi FAIL vẫn giữ nguyên. Các phản ví dụ/miss không được đổi thành TN để tăng metric.

Không có video độc lập có nhãn: Accuracy/Precision/Recall/F1, confusion matrix, false alarms/hour và latency AI thực tế **CHƯA ĐÁNH GIÁ**. Giữ mục tiêu Accuracy >80%, Precision/Recall/F1 >=80%, chưa tuyên bố đạt.

Video tương lai phải chia validation/test theo phiên, gồm chạm/không chạm/tay in sẵn/không tay, nhiều tay, rung/disconnect, điều kiện ánh sáng; khóa ngưỡng sau validation. Chấm event theo episode và khoảng thời gian có nhãn; ghi cả unavailable, track fragmentation, cảnh báo bỏ lỡ và thời gian đến ALERT. Suy luận ảnh 2D không chứng minh tay đã chạm mặt tranh.

Phase E kết thúc ở offline. Không tích hợp SQL Server/web, không chạy ESP32/GPU.
