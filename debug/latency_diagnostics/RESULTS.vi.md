# Kết quả chuẩn bị công cụ latency ArtGuard — offline

Ngày: 18/10/2026. Chỉ tạo file mới trong debug/latency_diagnostics/, đường dẫn đã được xác minh chưa tồn tại trước triển khai. Không gắn hook vào worker thật, không mở camera, không inference model, không truy cập database hoặc chạy website. Source v3 và các Phase B/C/D/E/F được giữ nguyên.

## 1. Kết quả kiểm tra thực tế

| Kiểm tra | Kết quả |
|---|---|
| Unit test có guard, Windows Python 3.14.7 | PASS: 176 test, 0 FAIL, 0 ERROR |
| Unit test có guard, WSL contacthands Python 3.7.16 | PASS: 176 test, 0 FAIL, 0 ERROR |
| Lệnh unittest discover riêng thư mục latency, WSL | PASS: 176 test, 0 FAIL, 0 ERROR |
| Import runtime model/camera/DB; network/process/file mutation trong test | Không có thao tác bị gọi; guard báo danh sách rỗng |
| AST cú pháp Python 3.7 và compile trong bộ nhớ | PASS: 14 file Python, không ghi bytecode |
| Liên kết tương đối trong README | PASS: 12/12 |
| JSONL mẫu qua CLI | PASS: 3 record hợp lệ, 0 dòng lỗi, chỉ SYNTHETIC_TEST |
| Benchmark camera, GPU, hiệu năng thực tế | NOT TESTED: chưa được phê duyệt |
| Hook worker, đồng bộ camera, ACK website | NOT AVAILABLE: cần tích hợp riêng |

Có 176 test khác nhau, chạy trên hai môi trường; không cộng thành 352 test độc lập. Phân bổ: schema 40, analyzer 51, CLI 16, ground truth 16, input quality 10, recorder/wrapper 43.

Test bao phủ timestamp tăng/giảm/trùng, clock khác nhau và map hết hạn/mơ hồ, capture UNKNOWN, thiếu stage, CUDA enqueue hoặc chưa synchronize, cold/warm, synthetic/real, ALERT/no ALERT, duplicate/stale/drop, GT thiếu/mâu thuẫn và event/ACK đến muộn trên frame thật. Wrapper giữ nguyên object trả về, tham số, số lần gọi và exception của hàm gốc trong các trường hợp đã kiểm thử.

Trong quá trình phát triển, đã sửa lỗi analyzer bỏ sót tính không đầy đủ của GT ở frame bị loại do chronology; giữ nguyên kỳ vọng test. Rà soát cuối còn tìm ra lỗi định dạng exception telemetry có __str__ bị lỗi, đã sửa wrapper mới và thêm hai regression test. Hai test mới về tuổi frame ban đầu dùng sai tên trường chữ hoa/thường; sửa tham chiếu, giữ kỳ vọng hành vi. Một lượt harness Windows lỗi do mock socket trước import SSL, đã sửa harness và chạy lại thành công. Không có sửa đổi source sản phẩm để làm test PASS.

## 2. File mới

- __init__.py, __main__.py: entrypoint thụ động.
- schema.py: hợp đồng timestamp/clock, duration và validation.
- recorder.py: ProcessClock, FrameTrace, writer độc quyền và thư mục run duy nhất.
- timing.py: wrapper quan sát, không tự import CUDA hoặc model.
- analyzer.py, cli.py: parser và thống kê offline.
- tests/__init__.py, tests/test_schema.py, tests/test_analyzer.py, tests/test_cli.py, tests/test_ground_truth.py, tests/test_input_quality.py, tests/test_recorder.py.
- [README.vi.md](README.vi.md): schema, cách dùng, vị trí hook và kế hoạch benchmark.
- [examples.synthetic.jsonl](examples.synthetic.jsonl): ba record hoàn chỉnh; không phải inference thật.
- [summary run đầu](runs/analysis_20261018T063755380082Z_348f1ff3/summary.json): giữ nguyên, không ghi đè.
- [summary mới](runs/analysis_20261018T064307038449Z_836259c2/summary.json): có thêm metric tuổi frame theo quyết định cuối frame.
- RESULTS.vi.md và [verification.json](verification.json): báo cáo và bằng chứng kiểm tra.

Tổng 20 file mới. Không có file đã tồn tại trước lượt triển khai bị sửa.

## 3. Hợp đồng đo và kết quả mẫu

Record FRAME có source_id/session_id/frame_id, data_kind, phase, frame_status, clock_domains, clock_sync, timestamps, execution_modes, prediction_ready_confirmed và alerts. Timestamps dùng value_ns với clock_id/epoch; status MEASURED/ESTIMATED/UNKNOWN/NOT_AVAILABLE và uncertainty_ns. Không dùng mtime làm capture timestamp. Chỉ map clock bằng hiệu chuẩn tường minh còn hiệu lực; phép map được báo ESTIMATED.

Các mốc đã có trong API: capture, request/receive/publish, read start/end, decode start/end, stream2/stream1, prediction ready, tracking/temporal và decision cuối frame. Event có decision, committed, evidence ready và ACK delivered/visible. t_decision_end là tùy chọn cho cả frame không ALERT, không suy ra từ tracking hay I/O. CUDA synchronized wall và CUDA event execution tách biệt; enqueue chưa sync không được coi là execution.

Analyzer báo n/p50/p95/p99 riêng từng stage và nhóm source/session/cold-warm/synthetic-real, cadence quan sát, tuổi frame, duplicate/stale/drop, ALERT duy nhất và missed event/UNKNOWN khi GT đủ điều kiện. Endpoint thiếu hoặc clock không hợp lệ cho n=0 và percentile null; không chèn số 0 hoặc cộng percentile các stage.

Ba record mẫu có tổng một event SYNTHETIC_TEST, không có mẫu delivery/visibility. GT là UNKNOWN/PARTIAL nên missed_events=null. Capture chưa biết ở record cold; hai khoảng capture→receive warm là số giả lập kiểm tra parser, tuyệt đối không dùng làm latency máy. Không có sample REAL_INFERENCE. Tuổi frame theo t_decision_end trong fixture chưa có, giữ n=0 đúng hợp đồng.

## 4. Cách gắn vào pipeline sau này

API wrapper đã sẵn sàng nhưng chưa được cài vào v3/D/E/F. Bước tích hợp cần tạo launcher/binding riêng và kiểm thử parity trước: một ProcessClock dùng chung giữa các frame; producer cung cấp timestamp và domain; observer gọi cùng hàm, cùng input/output, không sửa threshold/entry/tracking/temporal.

v3 cv2.imread gộp read/decode nên không tách số đo nếu chưa có hook được duyệt. Đo stream2 tại model2; đo stream1 tại model forward sau stream2, không gán thời gian outer predictor cho riêng stream1. Prediction ready cần tensor/CPU đã thực sự sẵn sàng. Ghi decision tại alert_started, commit sau store thành công, evidence sau ghi/link thành công. I/O và synchronizing có thể thay đổi lịch xử lý, cần đo overhead và parity trên dữ liệu thật.

Capture time cần nguồn thật và đồng bộ camera/Windows/WSL. HTTP/file publisher và ACK từ website cần tích hợp thêm. Commit không phải delivery; render ACK không chứng minh người dùng đã đọc. ACK muộn không được rewrite frame_id cũ: có thể gắn vào frame thật tiếp theo; nếu không còn frame cần thiết kế lifecycle record riêng, hiện chưa hỗ trợ. Không tạo frame giả để bổ sung ACK.

## 5. Lệnh tái lập và benchmark được đề xuất

Đã chạy lệnh test offline dưới WSL:

```bash
cd /mnt/c/Users/LEGION/Pbl4
/home/legion/miniconda3/envs/contacthands/bin/python -B -m unittest discover -s debug/latency_diagnostics/tests -t .
```

Đã chạy CLI Windows phân tích fixture với --output-root; lệnh tương đương trong WSL:

```bash
/home/legion/miniconda3/envs/contacthands/bin/python -B -m debug.latency_diagnostics analyze --input debug/latency_diagnostics/examples.synthetic.jsonl --output-root debug/latency_diagnostics/runs
```

Lệnh baseline inference giới hạn dưới đây CHỈ ĐỀ XUẤT, CHƯA CHẠY, cần phê duyệt GPU riêng và xác minh JPEG/config/ROI/weights trước:

```bash
/home/legion/miniconda3/envs/contacthands/bin/python -B debug/alert_diagnostics/run_inference.py --allow-inference --frame-file data/camera_frame.jpg --config-json debug/alert_diagnostics/config.baseline.json --device cuda --poll-interval 0.5 --max-frames 30 --max-seconds 120
```

Runner cũ chỉ log schema cũ và không tạo đủ số đo từng stage. Không đưa log đó vào analyzer mới hoặc gọi đó là benchmark đầy đủ. Config baseline còn ROI thử nghiệm; không coi đã hiệu chuẩn. --max-seconds chỉ kiểm tra giữa các lời gọi, không ngắt được inference đang treo. Chưa có lệnh live benchmark schema mới; cần binding được duyệt trước.

## 6. Overhead và giới hạn đánh giá

Overhead CHƯA ĐO: lấy monotonic/tạo stamp, deep copy/validate record, JSON serialization, ghi và flush log, GPU synchronize. Chưa có cơ sở ước lượng ms; không lấy thời gian unit test làm overhead. Đo A/B cùng input/config/cadence và điều kiện nhiệt, xen kẽ thứ tự, báo timer-only/serialization/I/O/sync riêng, p50/p95/p99 và parity quyết định/số frame xác nhận. Đồng bộ CUDA có thể phá overlap và làm chậm run được đo.

Analyzer hiện giữ record trong RAM; không phải streaming giới hạn bộ nhớ. Clock calibration, readiness, ACK và ground truth do observer cung cấp, công cụ không tự xác minh tính đúng vật lý. Thống kê missed event phụ thuộc episode hoàn tất/association reviewer và phạm vi quan sát đầy đủ; UNKNOWN không thành NO_TOUCH.

ESP32-CAM OV3660 phải gắn trực tiếp sát mép trên tranh, nhìn xiên xuống; góc, FOV, vùng mù và độ phủ chưa đo. Một consumer camera chính; camera phụ bên hông chỉ xác minh GT và sai số đồng bộ. Chưa đo latency contact→decision/commit/delivery, Accuracy/Precision/Recall/F1 hoặc false alerts/hour trên video thực. Mục tiêu <500ms, tham vọng 300ms và Accuracy >80% đều CHƯA ĐÁNH GIÁ.

## 7. Bảo vệ Git và file

Branch trước/sau: test-web. HEAD trước/sau: aca33ee901bd12f527499c20222100b104d0d6b1. git status --short giống trước (debug/ đã untracked từ trước nên thư mục mới không tạo thêm dòng short status). Ba tracked file sửa sẵn vẫn là inference/dataset_collector.py, web/.env.example, web/frontend/package-lock.json; mọi untracked sẵn có được giữ.

Đối chiếu ngoài thư mục mới: SHA-256 nội dung 1.163 file và size/mtime_ns của 15.330 file khớp trước/sau; 0 lỗi đọc, 0 reparse bị bỏ qua. Nội dung dependency/cache/build, database và secret thật không được hash; metadata vẫn được so sánh. Không mở database. Không đọc nội dung .env thật. Dataset/môi trường bên ngoài project không được hash toàn bộ; không có thao tác ghi vào đó.

- Content aggregate trước/sau: 8bdf9bde70e8c4867762d9217e66c062d254b7caf5adec4456c11254c34b5b1f
- Metadata aggregate trước/sau: 79a06f55291bf151f7ae366aac729a2d9f5b394463e5e526565d55c546de340c
- models/combined_data_model.pth trước/sau: c03f38a947d426b39b7538a5478f823799d98b34e0fb299ec35a6520342a342a
- inference/dataset_collector.py: 5110352949dc3cd6ec3ea79601daec947fc65e523eb4e6c6b288ee8e43ad65ed, giữ hai chỉnh sửa import đã có.

Aggregate là SHA-256 của JSON danh sách path/hash hoặc path/size/mtime_ns được sắp xếp; không phải hash nội dung nối tùy ý. Chi tiết đầu ra test, Git status và snapshot xem verification.json.

## 8. Điểm dừng

Hoàn tất chuẩn bị công cụ offline. Chưa chạy camera, GPU/CPU model inference, training, website, SQL Server hoặc thay đổi môi trường; không commit/push. Bước tiếp theo cần phê duyệt riêng: binding quan sát độc lập và kiểm thử parity, trước khi benchmark camera/GPU.
