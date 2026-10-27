# Công cụ chuẩn bị đo latency ArtGuard — offline

Ngày chuẩn bị: 18/10/2026 (Asia/Bangkok). Phạm vi hiện tại: chuẩn hóa timestamp, ghi trace thụ động, phân tích JSONL và kiểm thử bằng dữ liệu **SYNTHETIC_TEST**. Chưa mở camera, chưa inference CPU/GPU, chưa tích hợp worker, database hoặc website.

## 1. Trạng thái và giới hạn

- Source sản phẩm, worker v3 và Phase B/C/D/E/F được giữ nguyên.
- Bộ công cụ dùng thư viện chuẩn, tương thích Python 3.7; không import PyTorch, Detectron2, OpenCV hoặc backend để phân tích log.
- Chưa có hook chạy thật cho từng stream, điểm quyết định ALERT, commit, delivery hoặc hiển thị. Không có lệnh live benchmark mới trong CLI này.
- Ba dòng trong [examples.synthetic.jsonl](examples.synthetic.jsonl) chỉ là fixture minh họa. Mọi số thời gian đều được đặt có chủ đích, **không phải kết quả camera, AI hay tốc độ máy**.
- Mục tiêu dưới 500 ms, tham vọng 300 ms và Accuracy >80% đều **CHƯA ĐÁNH GIÁ**. Unit test không phải phép đo độ chính xác nhận diện.

## 2. Hợp đồng JSONL

Mỗi dòng là một FRAME theo [schema.py](schema.py). Trường bắt buộc:

| Trường | Ý nghĩa |
|---|---|
| schema_version / record_type | Phiên bản 1, FRAME |
| data_kind | SYNTHETIC_TEST hoặc REAL_INFERENCE; không gộp hai loại |
| source_id / session_id / frame_id | Nguồn, phiên quay và định danh frame từ producer; không suy ra thời điểm chụp từ tên file |
| phase | COLD_START, WARM, NOT_APPLICABLE hoặc UNKNOWN; cold/warm không gộp percentile |
| frame_status | PROCESSED, DUPLICATE, STALE, DROPPED, MISSING, ERROR hoặc REJECTED; phải do observer báo thật |
| clock_domains / clock_sync | Clock có kind và epoch_id; ánh xạ clock chỉ dùng khi có hiệu chuẩn tường minh |
| timestamps | Các mốc của frame, được phép thiếu hoặc NOT_AVAILABLE |
| execution_modes / prediction_ready_confirmed | Ý nghĩa timer inference và bằng chứng prediction đã sẵn sàng |
| alerts | Danh sách event của frame; tách event mới với cảnh báo vẫn active |
| gpu_intervals | Tùy chọn; duration CUDA event có trạng thái synchronized |
| ground_truth | Tùy chọn; nhãn độc lập, episode và association do reviewer xác minh |

Một stamp có đúng các trường:

```json
{"status":"UNKNOWN","value_ns":null,"clock_id":null,"method":null,"uncertainty_ns":null,"reason":"source_did_not_supply_capture_timestamp"}
```

| status | Quy tắc |
|---|---|
| MEASURED | Đo trực tiếp bằng observer ghi ở method; có value_ns, clock_id, uncertainty_ns |
| ESTIMATED | Có nguồn ước lượng rõ trong method và uncertainty_ns; không ghi thành số đo trực tiếp |
| UNKNOWN | Giá trị cần biết nhưng nguồn không cung cấp hoặc không xác định, ví dụ capture timestamp |
| NOT_AVAILABLE | Hook/tín hiệu xác nhận chưa có, hoặc không đủ dữ liệu cho phép tính stage |

UNKNOWN/NOT_AVAILABLE có value_ns, clock_id, method, uncertainty_ns bằng null và reason không rỗng. Không dùng số 0 thay giá trị chưa biết. Cả bốn trạng thái là tính chất của timestamp, độc lập với data_kind: fixture có thể chứa stamp MEASURED giả lập nhưng record vẫn phải SYNTHETIC_TEST.

Trích đoạn minh họa **không phải record hoàn chỉnh để đưa vào parser**; ba record đầy đủ nằm trong examples.synthetic.jsonl:

```json
{"data_kind":"SYNTHETIC_TEST","phase":"WARM","frame_id":"SYNTHETIC_TEST_FRAME_2","alerts":[{"event_key":"SYNTHETIC_TEST_EVENT_001","new_event":true}]}
```

### Clock và đồng bộ

Duration nội bộ dùng monotonic nanosecond. clock_id phải phân biệt domain/process; epoch_id phải đổi khi process, camera hoặc bộ đếm khởi động lại. Không tái dùng clock_id qua epoch khác để nối cadence.

Trong cùng domain, chỉ trừ khi end >= start. Khác clock: mặc định trả NOT_AVAILABLE. Hợp đồng clock_sync cho phép một offset cố định tường minh:

```json
{"sync_id":"CALIBRATION_ID","from_clock":"SOURCE_CLOCK","to_clock":"HOST_CLOCK","offset_ns":1000000,"uncertainty_ns":500000,"valid_from_ns":1000000000,"valid_to_ns":2000000000,"method":"APPROVED_SYNC_METHOD"}
```

Ví dụ cấu trúc trên là minh họa, không phải hiệu chuẩn của ESP32. Công thức: t_to = t_from + offset_ns. Cả hai đầu khoảng đo phải nằm trong cửa sổ hiệu chuẩn theo clock from; timestamp chuyển đổi phải được báo ESTIMATED và cộng sai số hai stamp cùng sai số hiệu chuẩn. Ánh xạ hết hạn, mơ hồ hoặc không tồn tại không cho phép tính latency. Không nối nhiều ánh xạ tự động; không coi offset bằng 0 là đã đồng bộ. Drift chưa được mô hình hóa bằng một offset phải làm cửa sổ hiệu lực ngắn lại và đo lại sau.

**Không dùng file mtime, host receive time hay thời điểm model trả kết quả làm t_capture.** Nếu firmware/producer chưa cấp capture stamp thật, giữ UNKNOWN. UTC/wall clock chỉ nên là metadata phụ cho đối chiếu; không trừ trực tiếp wall clock với monotonic.

### Danh sách mốc

Frame:

```text
t_capture
t_request_start -> t_receive_complete -> t_file_publish
t_worker_read_start -> t_worker_read_end
t_decode_start -> t_decode_end
t_inference_start
t_stream2_start -> t_stream2_end
t_stream1_start -> t_stream1_end
t_prediction_ready -> t_tracking_end -> t_temporal_end
```

Mỗi event trong alerts có event_key, new_event, timestamps và acknowledgements:

```text
t_alert_decision -> t_event_committed -> t_evidence_ready
t_alert_delivered / t_alert_visible: chỉ có khi thực sự nhận acknowledgement
```

new_event=false biểu thị event vẫn active; không tăng số ALERT thêm một lần. Nhiều tay có thể sinh nhiều event trên một frame. Event key phải ổn định và không ghép nhầm giữa source/session.

MEASURED/ESTIMATED cho t_alert_delivered yêu cầu acknowledgement kind DELIVERY_ACK; t_alert_visible yêu cầu DISPLAY_RENDER_ACK. Signal phải có signal_id, observer và event_key trùng event. Không suy ra delivery từ commit, HTTP request được gửi, trạng thái ALERT trong RAM hoặc ghi ảnh. DISPLAY_RENDER_ACK chỉ chứng minh ứng dụng đã báo render; không chứng minh mắt người thực sự quan sát cảnh báo.

### CUDA và cold start

- CPU_ONLY: khoảng wall monotonic của callback CPU.
- CUDA_ENQUEUE_ONLY: có thể chỉ là enqueue phía CPU; không phải thời gian thực thi GPU.
- CUDA_SYNCHRONIZED_WALL: synchronize trước/sau callback; bao gồm CPU, chờ, xử lý và GPU liên quan. **Không phải kernel time thuần GPU.**
- CUDA event interval chỉ dùng làm số đo GPU khi method=CUDA_EVENT và synchronized=true. Không tự coi cờ MEASURED là đủ khi chưa đồng bộ.
- COLD_START gồm lần đầu chạy/chuyển trạng thái được observer đánh dấu. Cần ghi riêng thời gian khởi tạo model và warmup ở log benchmark tương lai; không trộn vào WARM và không âm thầm bỏ cold start.
- t_prediction_ready chỉ được xác nhận khi tensor cần thiết đã sẵn sàng CPU/được chờ đúng cách; việc callback predict trả về chưa luôn chứng minh điều đó.

## 3. API thụ động và hướng gắn hook

[recorder.py](recorder.py) có các API cụ thể:

```python
ProcessClock(clock_id=None, epoch_id=None, read_ns=None)
FrameTrace(source_id, session_id, frame_id, data_kind, phase, clock=None)
trace.mark(stage)
trace.set_capture(stamp)
trace.add_clock(clock_id, kind, epoch_id)
trace.add_sync(mapping)
trace.prediction_ready(confirmed=False)
trace.add_alert(event_key, new_event=True)
trace.mark_alert(event_key, stage, stamp=None)
trace.acknowledge(event_key, stage, stamp, signal_id, observer)
trace.snapshot()
```

Tạo **một ProcessClock dùng lại giữa các frame của cùng process/epoch**, truyền qua clock=; nếu để mỗi FrameTrace tự tạo clock riêng thì không có cùng domain để đo cadence liên-frame. Tất cả mốc ban đầu NOT_AVAILABLE, riêng capture UNKNOWN. prediction_ready mặc định confirmed=False; không đánh dấu ready chỉ vì có callback trả về. acknowledge bắt buộc stamp do observer bên ngoài cung cấp, không tự lấy local clock-now để giả lập delivery.

[timing.py](timing.py) cung cấp wrapper:

```python
observe_call(fn, trace, start_stage, end_stage, args=(), kwargs=None,
             execution_stage=None, execution_mode="UNKNOWN",
             synchronize=None, prediction_ready_confirmed=False,
             event_key=None, end_predicate=None)
```

Wrapper trả đúng object/cùng business exception, không thay đổi input/output model hoặc logic xác nhận. Khi end_stage là mốc lifecycle ALERT, phải có end_predicate(result) chứng minh thao tác tương ứng đã thành công; return bình thường, đặc biệt return None, **không tự chứng minh commit**. Predicate không có/false/lỗi làm mốc thành NOT_AVAILABLE. Delivery/visibility vẫn cần API acknowledge riêng, không qua timer callback.

Synchronize chỉ được gọi qua callback truyền vào; thư viện này không tự import CUDA. Probe telemetry lỗi làm vô hiệu hóa mốc bị ảnh hưởng thành NOT_AVAILABLE, ghi issue và giữ return/exception business. Callback synchronize lỗi khiến execution mode UNKNOWN; không chuyển thành số đo GPU hợp lệ. Sink/telemetry failure là mất số đo phải báo, không phải thao tác thành công.

**API hook đã chuẩn bị; chưa được cài vào worker thật.** Log đồng bộ, clock mapping, acknowledgement và nhãn/association của reviewer là bằng chứng ngoại vi được tin theo hợp đồng; analyzer không xác minh được đồng bộ vật lý, nguồn gốc ACK hay chất lượng ground truth.

Log cần tạo file mới bằng cơ chế exclusive, dưới runs và thư mục run duy nhất; không mở log cũ ở chế độ ghi đè. Dữ liệu ground truth/prediction và các trace cũ không bị chỉnh sửa. Đối với sink lỗi, phải giữ lỗi business gốc và log tình trạng instrumentation không đầy đủ; không giả tạo mốc thành công. Overhead instrumentation vẫn có thể ảnh hưởng lịch xử lý nên cần A/B, dù không sửa thuật toán.

**Chưa monkeypatch hoặc gắn wrapper vào v3 ở lượt này.** Vị trí đề xuất cho lần tích hợp riêng được duyệt:

| Mốc/hook | Ràng buộc |
|---|---|
| Request/receive/file publish | Bọc producer/capture thực; chỉ file-watch thì các mốc producer chưa cung cấp là NOT_AVAILABLE |
| Capture | UNKNOWN cho đến khi nguồn cung cấp timestamp, domain và cách đồng bộ |
| Worker read/decode | v3 đang dùng cv2.imread gộp đọc và decode; không suy ra hai khoảng riêng. Cần hook được duyệt hoặc giữ các mốc chưa tách là NOT_AVAILABLE |
| Stream 2 | Bọc callback model2 tại inference_second_stream, không bọc toàn outer predictor rồi gọi đó là stream 2 |
| Stream 1 | Bọc lời gọi model stream 1 sau khi stream 2 hoàn tất; outer predictor chứa cả hai nên không được ghi hai lần cùng khoảng |
| Prediction ready | Sau bước chuyển bbox/score/contact sang Python/CPU cần thiết và xác nhận hoàn tất |
| Tracking / temporal | mark sau update_tracks và sau vòng advance_track_contact riêng biệt |
| ALERT decision | Đúng lúc advance_track_contact báo alert_started cho từng track/event; không lấy thời điểm ghi preview thay cho quyết định |
| Event committed | Chỉ sau EventStore.record_event trả về thành công và commit thực sự xong |
| Evidence ready | Sau ghi nguyên tử evidence và liên kết metadata thành công; lỗi một bước không được gán ready |
| Delivery / visible | Giữ NOT_AVAILABLE đến khi consumer bên ngoài gửi acknowledgement đúng event |

Nguồn tham khảo được giữ nguyên: [worker v3](../../src/realtime_worker_integrated_v3.py), [hai stream](../../src/detect_compat.py), [EventStore](../../src/services/event_store.py), [D](../alert_diagnostics/v4/phase_d/pipeline_d.py), [E](../alert_diagnostics/v4/phase_e/offline_pipeline.py), [F](../alert_diagnostics/v4/phase_f/pipeline_f.py).

Một frame có thể quyết định ALERT trước preview/commit/evidence. Tách ba ý nghĩa: **decision**, **publication bền vững**, **acknowledged delivery/visibility**. Không thay ngưỡng ContactHands, ROI entry, tracking timeout, số frame/duration xác nhận để rút ngắn timer.

## 4. Phân tích offline và giới hạn thống kê

[analyzer.py](analyzer.py) đọc record hợp lệ, tách data_kind và phase, trả số mẫu cùng p50/p95/p99 theo stage có đủ bằng chứng. Giá trị thiếu giữ NOT_AVAILABLE; không chèn 0, không nội suy stage, không cộng các percentile thành percentile end-to-end. Mẫu ít chưa đủ kết luận tail latency; cần xem count và reason bị từ chối.

Các khoảng gồm cadence/FPS quan sát, capture→receive nếu clock đồng bộ, receive→decode, hai stream/tổng inference, tracking/temporal, decision→commit, commit→delivery, tuổi frame khi quyết định và evidence. Clock giảm/khác epoch, duplicate ID hoặc frame không hợp lệ không được cộng thành mẫu inference hợp lệ. FPS quan sát từ frame đã ghi khác sensor FPS; không suy số dropped frame từ khoảng trống nếu producer không cung cấp sự kiện drop.

Frame status DUPLICATE/STALE/DROPPED/MISSING/ERROR/REJECTED và issue phải giữ lại. Stage không có endpoint tương thích không sinh metric. Timestamp AI quyết định không được tính như cảnh báo đã đến UI.

Ground truth chỉ được ghi sau gán nhãn độc lập. TOUCH, NEAR_NO_TOUCH, NO_TOUCH, UNKNOWN giữ nguyên; **UNKNOWN không chuyển thành NO_TOUCH**. Missed event chỉ có thể đếm cho TOUCH episode đã hoàn tất, có association reviewer và phạm vi quan sát đầy đủ. Nếu chưa có GT: số missed/accuracy/precision/recall/F1 là NOT_AVAILABLE, không phải 0. Một vài fixture không chứng minh mục tiêu >80%.

Nhãn GT của frame DROPPED/MISSING/REJECTED được giữ để đánh giá episode; các frame đó không tạo duration inference hay bằng chứng ALERT. GT mâu thuẫn/excluded hoặc episode nằm qua nhiều nhóm cold/warm giữ trạng thái PARTIAL, không tự thành missed=0 toàn cục. Người đánh giá phải kiểm tra phạm vi quan sát, sự hoàn tất episode và association độc lập.

Parser giới hạn từng dòng 1 MiB nhưng analyzer hiện giữ records/report trong RAM. Đây **không phải phân tích streaming có bộ nhớ giới hạn theo thời gian phiên**. Chỉ phân tích các run offline có dung lượng được giám sát; phiên dài cần chia run có ranh giới episode rõ và thiết kế tổng hợp riêng trước. Không nối các percentile của từng phần bằng trung bình.

Chạy offline trong WSL từ repository:

```bash
cd /mnt/c/Users/LEGION/Pbl4
/home/legion/miniconda3/envs/contacthands/bin/python -B -m debug.latency_diagnostics analyze --input debug/latency_diagnostics/examples.synthetic.jsonl --stdout
```

Lệnh trên chỉ phân tích SYNTHETIC_TEST và in stdout. Muốn artifact mới, thay --stdout bằng:

```text
--output-root debug/latency_diagnostics/runs
```

CLI tạo run mới dưới thư mục được phép, không ghi đè summary cũ. Không đổi fixture thành REAL_INFERENCE để tạo benchmark. Không chạy toàn bộ pytest repository vì có module tạo model khi import.

## 5. Buổi benchmark thật sau khi được duyệt riêng

### Điều kiện

ESP32-CAM OV3660 phải gắn **trực tiếp sát mép trên khung tranh**, nhìn **xiên xuống dọc mặt tranh**. Góc nghiêng, FOV, độ phủ và vùng mù **chưa đo**; không điền giá trị giả định. Hiệu chuẩn ROI theo ảnh thật và ghi phần ngoài FOV. Một consumer ESP32 chính; downstream dùng snapshot/trace chung, không tự mở thêm stream. Camera phụ bên hông chỉ để xác minh TOUCH/NEAR_NO_TOUCH và đồng bộ GT. Không sửa firmware, CUDA/Conda, checkpoint hoặc dataset để chạy benchmark.

### Lệnh baseline tương lai — KHÔNG CHẠY Ở LƯỢT CHUẨN BỊ

Runner có sẵn [run_inference.py](../alert_diagnostics/run_inference.py) hỗ trợ file-watch giới hạn và explicit --allow-inference. Ví dụ cú pháp tồn tại:

```bash
cd /mnt/c/Users/LEGION/Pbl4
/home/legion/miniconda3/envs/contacthands/bin/python -B debug/alert_diagnostics/run_inference.py --allow-inference --frame-file data/camera_frame.jpg --config-json debug/alert_diagnostics/config.baseline.json --device cuda --poll-interval 0.5 --max-frames 30 --max-seconds 120
```

Chỉ dùng khi nhóm đã phê duyệt GPU riêng, có JPEG producer và local weights sẵn có; config.baseline.json là cấu hình chẩn đoán cũ, ROI thử nghiệm **không được coi là đã hiệu chuẩn**. Không ghi đè file cấu hình để chạy. --max-seconds kiểm tra giữa các lời gọi, không hủy được inference đang treo; buổi chạy cần giám sát/watchdog được duyệt.

Runner cũ tạo log tổng inference và frame processing theo **schema cũ**, thiếu nhiều stage. **Không đưa log cũ vào analyzer mới và không báo là đã đo đầy đủ.** Để có benchmark schema mới phải phê duyệt binding độc lập, kiểm thử hook/clock/ack và output mới trước; công cụ hiện tại chưa có live command tương ứng. Không chạy camera hay dịch vụ web để tạo acknowledgement giả.

### Quy trình và overhead

1. Khóa config/model/ROI; ghi version, clock domains, source cadence, GPU/CPU workload và run ID.
2. Đo cold init/first inference riêng; warmup có ghi nhận, không lẫn với warm sample.
3. Đo lặp cùng input/cadence bằng baseline và instrumented, đảo thứ tự A/B; cùng điều kiện nhiệt/GPU workload. Giữ quyết định, event ID/số frame xác nhận và error parity.
4. Tách chi phí timer, wrapper, GPU synchronize, serialization và ghi log; synchronize có thể làm mất overlap GPU nên phải báo rõ tác động.
5. Nếu dùng writer async sau này, queue có giới hạn, frame/event ID bất biến, báo dropped telemetry; không cho writer chặn/mất ALERT âm thầm. Chưa triển khai async/live writer ở bước này.
6. Báo count, p50/p95/p99, error/UNKNOWN, frame age, duplicate/drop, latency contact GT→decision→commit→delivery; GT có sai số đồng bộ. Không lấy latency chỉ trên các event thành công để che missed event.
7. Chạy chạm/không chạm, tay in sẵn, không tay, nhiều tay, che khuất, mất kết nối, tốc độ/ánh sáng khác nhau. Chia validation/test theo phiên quay, khóa tham số trước test độc lập.

**Overhead hiện tại: CHƯA ĐO**, không có ước lượng ms được bảo chứng. Dưới 500 ms/300 ms chỉ được đánh giá sau số đo end-to-end đủ tin cậy; không giảm temporal hay score để làm đẹp latency. Chưa có dữ liệu thật để đánh giá Accuracy/Precision/Recall/F1 >80% hoặc tác động False Positive/False Negative.

## 6. Điểm dừng

Bộ công cụ hiện chỉ sẵn sàng phân tích trace offline và kiểm thử hợp đồng đo. Tích hợp v3/D/E/F, hook inference thật, hiệu chuẩn đồng hồ, observer UI và benchmark camera/GPU đều **CHƯA THỰC HIỆN / CHỜ PHÊ DUYỆT RIÊNG**.


## Mốc quyết định cho frame không phát ALERT

`t_decision_end` là mốc tùy chọn, ghi trực tiếp khi việc xét trạng thái của frame đã hoàn tất, kể cả khi không phát ALERT. Metric `frame_age_at_decision_all_frames` chỉ có dữ liệu khi cả `t_capture` và mốc này hợp lệ, cùng clock hoặc có ánh xạ đồng bộ được khai báo. Không dùng thời điểm tracking, ghi evidence hoặc trả về hàm để tự điền mốc này. Metric tuổi frame theo từng event vẫn dùng `t_alert_decision`; cả hai đều không phải thời điểm người dùng nhìn thấy cảnh báo.


### Giới hạn ghi nhận ACK đến muộn

Schema hiện tại chỉ có record FRAME. Không ghi lại cùng frame_id với nội dung mới để thêm ACK: analyzer sẽ coi đó là duplicate mâu thuẫn và loại khỏi thống kê. ACK thật có thể gắn với event_key trên một frame thật đến sau, như trường hợp đã được kiểm thử. Nếu không có frame tiếp theo, cần giữ trace chưa chốt hoặc thiết kế record lifecycle/ACK riêng ở bước tích hợp được duyệt; hiện chưa có cơ chế đó. Không tạo frame giả chỉ để chứa ACK, không lấy thời điểm ghi log làm thời điểm delivery/visible.
