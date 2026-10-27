# Kết quả chẩn đoán ALERT — 17/10/2026

Đã chạy test logic bằng Python 3.7.16 trong Conda contacthands, không nạp model hoặc camera.

## Kiểm thử thực tế đã chạy

Lệnh: /home/legion/miniconda3/envs/contacthands/bin/python -B debug/alert_diagnostics/run_logic_tests.py

17/17 PASS, 0 failure/error, thời gian unittest 0.047 giây.
Artifacts: runs/logic_20261017T025850117889Z_67ecfc78/
83 frame đầu vào logic được kiểm soát, 9 scenario có trace.
logic_only.sqlite3 có 3 event CONTROLLED_LOGIC_TEST_NOT_AI từ B/E/F.
Không có ảnh giả hoặc nhãn dataset được tạo, không có số liệu chất lượng AI.

| Trường hợp | Quan sát |
|---|---|
| A — xuất hiện sẵn trong ROI | Cùng ID, đủ 5/5 nhưng entry=false; CANDIDATE |
| B — từ ngoài vào, rồi giữ | Entry=true, ALERT tại frame dương thứ ba; đúng một event |
| C — đi chậm qua biên | Bước 0,01 < ngưỡng 0,015; entry không bật; CANDIDATE |
| D — frame cách 1,01s | Timeout 1s; ID mới mỗi frame, lịch sử chỉ một frame |
| E — 3/5 hợp lệ | Cửa sổ true/false/true/false/true phát ALERT |
| F — hai frame ≥0,85 | Sau entry phát ALERT bằng fast path, trước khi đủ ba frame |
| G — tay tĩnh sẵn trong tranh | Score 0,99 vẫn không phát ALERT |

PASS là khớp hành vi code hiện tại, kể cả các hạn chế được tái hiện.
Các test bổ sung kiểm tra score thấp, miss detection, schema/defaults,
env overrides, exclusive-create, output isolation, inference opt-in,
giới hạn thời gian/số frame, tracking probe và timer.

--help thoát 0. Chạy runner thiếu --allow-inference thoát 2, không tạo run mới.
Local second-stream cache đã có; chưa nạp weights.
Cú pháp AST của cả bốn file Python mới hợp lệ.
Không tạo bytecode trong diagnostics.
git diff --check PASS; cảnh báo LF/CRLF trên file có sẵn không phải lỗi whitespace.

## File mới

- common.py: gọi hàm sản phẩm, schema, output isolation, dữ liệu log.
- test_logic.py: 17 test.
- run_logic_tests.py: runner logic, trace, timeout sweep và SQLite logic riêng.
- run_inference.py: runner opt-in, bounded file-watch, instrumentation.
- config.baseline.json: rectangle test bật, normalized boolean, đúng schema.
- README.vi.md: hướng dẫn UTF-8 chính thức.
- RESULTS.vi.md: báo cáo này.
- README.md và RESULTS.md: bản đầu bị mất dấu khi truyền stdin, giữ nguyên không ghi đè.
- protected_files.sha256.json và verification.json: báo cáo đối chiếu ban đầu.
- protected_files.sha256.corrected.json và verification.corrected.json: kết quả cuối.
- runs/logic_20261017T025850117889Z_67ecfc78/summary.json
- runs/logic_20261017T025850117889Z_67ecfc78/logic_frames.jsonl
- runs/logic_20261017T025850117889Z_67ecfc78/timeout_sweep.json
- runs/logic_20261017T025850117889Z_67ecfc78/logic_only.sqlite3

Hai chuỗi hash baseline recovered/verified ở bản đầu bị sao chép sai
(960433a560 thay cho 960433960a), không phải worker thay đổi.
Đối chiếu output hash trước triển khai và Get-FileHash Windows độc lập:
11/11 file được bảo vệ giữ nguyên, gồm mọi worker, contact_logic,
checkpoint và hai file tracked đang sửa.
Giữ báo cáo đầu, dùng verification.corrected.json làm kết quả cuối.
Trạng thái Git cuối chỉ thêm debug/ ngoài các thay đổi có sẵn.

## Kết luận và giới hạn

Đã chứng minh ở mức hàm: thiếu entry chặn ALERT dù đủ history; đi chậm có thể bỏ entry;
timeout làm mất ID và lịch sử. Chưa chứng minh nguyên nhân của lần camera trước
vì config và database /tmp cũ không còn.

timeout_sweep.json có 16 tổ hợp timeout/gap kiểm soát. Với gap 1,01s,
timeout 1s mất track; 2s/3s giữ track và cho phép xác nhận.
Đây không phải thời gian inference thực. Giữ baseline 1s để đo trước;
ứng viên so sánh 2s/3s cần dựa trên p95/p99 tracking delta và kiểm tra ghép nhầm tay.

Không sửa hoặc bỏ ever_entered_roi. Hướng cần đánh giá là quỹ đạo tích lũy và
hysteresis giữa vùng ngoài/trong để bắt tay di chuyển chậm. Tay sinh sẵn trong ROI
cần bằng chứng nền/chuyển động độc lập, không chỉ OC cao; camera rung là trường hợp khó.
Video có nhãn vẫn cần để đo báo động giả.

Runner inference PREPARED / NOT RUN. Dùng _analyze_frame nguyên bản, wrapper trong bộ nhớ,
log UTC/mtime/SHA256, inference và tracking timing, score, overlap, ID/entry,
history, trạng thái và các gate chặn. Mỗi frame có preview mới, SQLite/evidence riêng.
Không mở ESP32 stream, không kết nối SQL Server, không tự tải weights.
Lệnh WSL chi tiết ở README.vi.md. Giới hạn 30 frame/120s kiểm tra giữa lời gọi;
timeout ngoài tiến trình giới hạn cứng hơn. Không có phép đo precision/recall/FPR/latency.

Bước tiếp theo đề xuất: phê duyệt một lượt baseline bounded từ nguồn file capture hiện có.
