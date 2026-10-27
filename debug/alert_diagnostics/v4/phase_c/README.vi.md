# ContactHands v4 — Giai đoạn C

Kiểm toán logic và chuẩn bị đánh giá độc lập; không chạy camera/GPU/database.
Ngày 17/10/2026. Mục tiêu thực nghiệm vẫn CHƯA ĐÁNH GIÁ.

## Kết quả cuối

103 test: 98 PASS, 5 FAIL, 0 ERROR.
40 regression cũ PASS; 26 phản ví dụ PASS; 25 kiểm thử số học/window PASS;
7 hợp đồng evaluator PASS; 5 quality gates FAIL thuộc 4 nguyên nhân gốc.
PASS characterization chỉ có nghĩa tái hiện đúng hành vi, không khẳng định camera tốt.
Không dùng expectedFailure hoặc thay đổi kỳ vọng để che các quality FAIL.

Artifacts cuối:
runs/audit_20261017T040801829320Z_b3c5e90d/
audit_summary.json, comparisons.jsonl, controlled_inputs.jsonl, các test-log .txt.
Có 75 dòng tổng hợp: 25 tình huống × timeout 1/2/3s.
Hai run trước được giữ nguyên; không gộp số lần chạy thành số test mới.

## Chạy lại

```bash
cd /mnt/c/Users/LEGION/Pbl4
/home/legion/miniconda3/envs/contacthands/bin/python -B \
  -m debug.alert_diagnostics.v4.phase_c.run_audit
```

Exit 1 là kết quả dự kiến hiện tại vì 5 yêu cầu chất lượng chưa đạt.
Runner vẫn hoàn tất tất cả suite, lưu artifact mới và xác minh hash.
Không chạy run_tests cũ để ghi lại artifacts Giai đoạn B.

## Đánh giá độc lập

metrics.py không import v3/v4. evaluate.py chỉ đọc CSV và tính metric,
không mở video/camera hoặc nạp model. CSV template chỉ có header, chưa có mẫu thật.
protocol.json định nghĩa grid 1s, quy tắc uncertain/missing và matching event.

```bash
python -B -m debug.alert_diagnostics.v4.phase_c.evaluate --help
```

Khi đã có dữ liệu thật được duyệt:

```bash
python -B -m debug.alert_diagnostics.v4.phase_c.evaluate \
  --manifest /path/to/real/video_manifest.csv \
  --intervals /path/to/real/annotation_intervals.csv \
  --events /path/to/real/contact_events.csv \
  --predictions /path/to/results/prediction_windows.csv \
  --alerts /path/to/results/alert_events.csv --split test
```

Output mới dưới phase_c/evaluations/<UTC>_<random>/metrics.json.
Lưu input SHA256/protocol để tái lập. Header-only manifest bị từ chối, không tạo metric.
Manifest cần labels_approved=yes, video SHA256, session/capture_group và split rõ ràng.
Không có prediction đủ coverage -> metric chính null/BLOCKED; không điền missing thành negative.
SHA trong manifest được kiểm tra format/trùng lặp, chưa tự xác minh nội dung video:
người thu thập phải tính/đối chiếu hash file thật.

## File

audit_scenarios.py, test_adversarial.py, test_quality_gates.py: phản ví dụ và quality gates.
metrics.py, test_metrics.py: công thức độc lập, confusion/coverage, event matching, latency và FA/hour.
evaluate.py, test_evaluator.py: hợp đồng CSV và split độc lập.
run_audit.py, __init__.py: runner và package.
protocol.json, 5 *.template.csv: chính sách và biểu mẫu trống.
baseline_test_review.json: rà từng test trong 40 test cũ.
protected_before.json/protected_verification.json: bảo vệ 45 file cũ.
AUDIT_REPORT.vi.md, COLLECTION_PROTOCOL.vi.md: phát hiện và quy trình đánh giá.
runs/: chỉ artifacts mới, không sửa các run cũ.

## Trạng thái sẵn sàng

Sẵn sàng logic/replay và chuẩn bị thu thập có giám sát sau phê duyệt.
Chưa sẵn sàng đánh giá end-to-end v4 hoặc dùng làm nguồn cảnh báo tin cậy:
chưa có adapter inference v4 thực, ROI thật chưa hiệu chuẩn, có quality FAIL,
chưa có video độc lập có nhãn và nguồn clock được xác minh.
Dừng ở Giai đoạn C, không tự chạy inference hoặc sửa logic để làm xanh test.
