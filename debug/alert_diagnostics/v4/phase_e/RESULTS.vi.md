# Kết quả Phase E — tích hợp ContactHands offline vào Phase D

## Kết luận

Pipeline offline hoạt động xuyên suốt: export pred_boxes/scores/pred_cats -> chuẩn hóa -> stability -> tracking/entry/temporal của D -> event và JSONL log.

Tích hợp không có sai khác core so với D trên các record đối chiếu được. **Chưa đạt toàn bộ quality gates:** vẫn có 2 FAIL phục hồi sau mất/lỗi frame ngay sau entry. Không sửa D hoặc expected assertions để biến chúng thành PASS.

Không chạy camera/GPU/SQL Server/web. Không sinh ảnh/evidence thật, không train, không cài môi trường, không commit/push.

## Kiểm thử thực tế

Ubuntu WSL, Python 3.7.16, Conda contacthands. B/C/D bất biến. Lượt đầy đủ lặp lại dưới runtime guard.

| Suite | PASS | FAIL | ERROR |
|---|---:|---:|---:|
| B/C frozen, 103 tests | 98 | 5 | 0 |
| D, 64 tests | 64 | 0 | 0 |
| E, 82 tests | 80 | 2 | 0 |
| Tổng, 249 tests | 242 | 7 | 0 |

B/C vẫn đúng năm FAIL cũ; không có regression bổ sung trong bộ D 64 test. 37 unit/contract E PASS; 45 test JSONL/file/scenario E có 43 PASS, 2 FAIL. Các số là test logic, không phải metric AI.

Runner và runtime_audit **exit 1**, giữ hai quality gates chưa đạt. Không dùng expectedFailure/skip hoặc nới ngưỡng model.

## Hai FAIL phải giữ lại

- OfflineCases.test_case_explicit_missing_frame
- OfflineCases.test_case_explicit_frame_error

Chuỗi input: tay .25 lúc 0s -> .30 lúc .2s -> .45 lúc .4s -> missing/error lúc .6s -> .45 lúc .8s.

D ước lượng velocity x=0.3125/s. Lúc .8s dự đoán centre .575, cách detection .45 là 0.125 > reacquire_distance=0.1. ID 0 không tái ghép; ID 1 mới nằm sẵn trong ROI không có entry. Tại 1.0s hai track gần nhau gây uncertain/retire; ID tiếp theo vẫn không có entry. Do đó 0 ALERT thay vì mục tiêu phục hồi 1.

Bằng chứng:
- missing_reacquisition_investigation.json lưu đầy đủ tracks/time/reason.
- phase_d/tracking_d.py:14 dự đoán vị trí; :35 dùng reacquire_distance; :40 kiểm tra khoảng cách.
- E thêm characterization kiểm tra đúng ID/entry và direct D mismatch=0.
- Hai ca stable_hold_missing_recovery/stable_hold_frame_error_recovery PASS khi có thêm quan sát ổn định trước dropout.

Đây là giới hạn hành vi D được phát hiện bởi input mới, không phải sai lệch conversion/adapter. Chỉ được sửa ở bản thử nghiệm kế tiếp nếu được duyệt; không đổi source D trong E.

## Replay và so sánh

31 kịch bản, 809 dòng JSONL qua file thật. 808 record so sánh accepted/state/tracks/events với D trực tiếp, **0 mismatch**. Một record malformed prediction không thể đưa thẳng vào D; adapter log reject và tạo barrier xóa bằng chứng. Không gọi đó là record đã so sánh thành công.

Replay file và process in-memory cũng khớp sau khi bỏ metadata line_number/hash. Core D dùng cùng prediction đã chuyển đổi; stability STABLE/MOVING được mô phỏng rõ ràng ở cả hai đường. Không coi simulated stability là bằng chứng camera thực.

| Kịch bản | Event | Mục tiêu logic | Thiếu so với kỳ vọng tiếp xúc kiểm soát |
|---|---:|---:|---:|
| slow_entry | 1 | 1 | 0 |
| initial_inside | 0 | 0 | 1 |
| printed_static | 0 | 0 | 0 |
| polygon_slow_entry | 1 | 1 | 0 |
| multiple_separate_hands | 1 | 1 | 0 |
| score_oscillation | 0 | 0 | 1 |
| missing_detection | 1 | 1 | 0 |
| two_bouts_same_entry | 1 | 1 | 1 |
| contact_moderate_1fps | 1 | 1 | 0 |
| contact_fast_1fps | 1 | 1 | 0 |
| contact_moderate_5fps | 1 | 1 | 0 |
| contact_fast_5fps | 1 | 1 | 0 |
| contact_moderate_10fps | 1 | 1 | 0 |
| contact_fast_10fps | 1 | 1 | 0 |
| contact_moderate_15fps | 1 | 1 | 0 |
| contact_fast_15fps | 1 | 1 | 0 |
| contact_moderate_30fps | 1 | 1 | 0 |
| contact_fast_30fps | 1 | 1 | 0 |
| crossing_0.0 | 0 | 0 | 1 |
| crossing_0.01 | 0 | 0 | 1 |
| crossing_0.03 | 0 | 0 | 1 |
| disconnect_alert_reconnect_inside | 1 | 1 | 1 |
| shake_recovery_requires_entry | 2 | 2 | 0 |
| separate_episodes_default_cooldown | 2 | 2 | 0 |
| explicit_missing_frame | 0 | 1 | 1 |
| explicit_frame_error | 0 | 1 | 1 |
| duplicate_stale_nonmonotonic | 1 | 1 | 0 |
| malformed_payload_barrier | 0 | 0 | 1 |
| unknown_stability_real_contact | 0 | 0 | 1 |
| stable_hold_missing_recovery | 1 | 1 | 0 |
| stable_hold_frame_error_recovery | 1 | 1 | 0 |

Cột kỳ vọng tiếp xúc do người viết kịch bản kiểm soát đặt, không phải nhãn video hoặc tiếp xúc vật lý đã được xác minh. Tổng shortfall=11 qua các kịch bản; không chuyển thành Recall/F1 hay tỷ lệ AI thực tế.

## Rủi ro FP/FN và trường hợp từ chối

- Ba crossing: 0 event, mỗi ca thiếu 1 kỳ vọng kiểm soát do identity uncertain. Oracle kiểm tra chủ ID, không dùng label trong matcher.
- Initial_inside: thiếu 1 kỳ vọng chạm thật vì chưa có outside->inside; cùng chính sách giữ an toàn trước tay in sẵn.
- UNKNOWN stability: 18/18 frame unavailable, thiếu 1 kỳ vọng; không tính như true negative.
- Disconnect/reconnect khi tay còn trong ROI: state đã xóa, không thừa hưởng entry, thiếu 1 kỳ vọng xác nhận lại.
- Missing/error sát entry: hai FAIL nêu trên, mỗi ca thiếu 1.
- Payload hỏng: xóa state, thiếu 1 kỳ vọng; không nội suy contact xuyên dữ liệu hỏng.
- Score dao động: thiếu 1 kỳ vọng vì chưa đủ hỗ trợ liên tục; không giảm ngưỡng để ép ALERT.
- Hai đợt chạm cùng entry: 1 event thay vì kỳ vọng 2. Episode mới sau exit + default cooldown 60s hoạt động, 2 event.
- Stability giả lập báo STABLE sai vẫn có thể làm phát sinh FP; chưa có extractor nền ảnh thật. Score Object-Contact + overlap 2D không chứng minh chạm tranh; tay đi ngang vẫn có thể FP nếu model trả score cao kéo dài.
- Không có watchdog/camera producer trong E; thiếu callback disconnect thì module không tự biết camera mất kết nối.
- JSON lỗi không xác định nguồn làm clear mọi nguồn: bảo thủ nhưng có thể giảm Recall nguồn khác.
- Replay hiện giữ log trong RAM để tổng hợp; export rất dài cần tối ưu streaming aggregation trước sử dụng quy mô lớn. Không benchmark latency/VRAM ở E.
- API nội bộ D _gate/_clear_state là phụ thuộc cần ổn định hóa sau; mọi file D khóa hash và test regression.

## Camera stability và khả năng kết nối thật

Interface riêng có STABLE/MOVING/UNKNOWN. Default UNKNOWN. Signal mô phỏng phải khớp source/session/frame/time/reference; không lấy STABLE từ frame trước.

Có serializer CPU-only duck-typed, không import Torch; lấy đúng ba trường từ Instances. Đã kiểm tra bằng stub CPU, từ chối device GPU. ContactHands thật chưa được gọi. Exporter sau cần nhận Instances đã về CPU từ inference được phê duyệt, bổ sung image_size/capture time/receive time/source/session, xuất toàn bộ detection trước ROI filtering.

Nguồn source đối chiếu: src/realtime_worker_integrated_v3.py:28-35; src/core/contact_logic.py:5; contact_head.py:77. Không sử dụng API detect đã lọc ROI/contact để làm mất bằng chứng ngoài ROI.

Đề xuất tiếp: background features ngoài ROI/foreground + optical flow forward/backward + robust affine/homography so calibration reference cố định. Thiếu texture/rung/mờ/parallax => UNKNOWN. Chưa triển khai hoặc xác minh trên video; không bật correspondence provider mặc định.

## Runtime, Git và hash

315 file được bảo vệ có SHA-256 trước/sau khớp, gồm source sản phẩm/v3/v4/C/D, toàn bộ artifacts D, checkpoint và các file web vốn đang thay đổi. Manifest protected_before.json, protected_after.json và final_verification.json.

Runtime audit lần lặp lại: không gọi SQLite connect, network connect, remove/unlink/rename/replace hoặc ghi ngoài E. Guard ghi nhận 0 attempted blocked operations. **sqlite3 chỉ được import gián tiếp bởi baseline v3/EventStore, không tạo EventStore hay mở DB.**

run_tests.py có inventory tên forbidden_runtime_modules_loaded quá nghiêm, liệt kê sqlite3. Không diễn giải trường đó là DB đã được truy cập; dùng runtime guard evidence để phân biệt import với side effect. Runner/artifacts đầu tiên giữ nguyên, không xóa/ghi đè.

Git status trước/sau giữ nguyên. git diff --check exit 0; cảnh báo LF/CRLF của src/services/alert.py có sẵn, file không đổi hash. New files đều nằm dưới E vốn thuộc debug/ untracked nên Git status không liệt kê từng file mới. final_verification có manifest riêng.

Hash không phải checksum toàn dataset hoặc SQL Server; không truy cập DB hay chỉnh sửa dataset. Repo ContactHands gốc bên ngoài PBL4 không bị sửa.

## File mới

Source E:
- __init__.py
- prediction_adapter.py
- stability.py
- offline_pipeline.py
- replay.py
- controlled_cases.py
- compare_phase_d.py
- test_adapter.py
- test_replay_io.py
- run_tests.py
- runtime_audit.py

Tài liệu: README.vi.md, RESULTS.vi.md.
Fixture: fixtures/slow_entry.*, polygon_slow_entry.*, unknown_stability_real_contact.* gồm JSONL + settings.
Bằng chứng: protected_before.json; build_inputs_01/02; preflight_01/02.json; missing_reacquisition_investigation.json; runs/; io_tests/; runtime_audits/; final_verification.json.
Giữ các lần chạy và ứng viên trước, không ghi đè artifacts.

Preflight đầu: 74 test, 72 PASS/2 FAIL. Preflight sau và chính thức: 82 test, 80 PASS/2 FAIL. Giữ nguyên hai kỳ vọng phục hồi chưa đạt; chỉ thêm ca hồi phục ổn định, characterization và I/O tests.

## Đánh giá AI độc lập

Accuracy >80%, Precision/Recall/F1 >=80%: **CHƯA ĐÁNH GIÁ**. Unit/contract và integration offline không phải đánh giá model. Chưa có video độc lập có nhãn, chưa có số latency thật hay false alarms/hour.

Chỉ hoàn thành Phase E offline. Dừng trước camera/GPU/SQL Server hoặc tích hợp sản phẩm.

### Artifacts official

- runs/offline_20261017T045603588287Z_349f7bed
- runtime_audits/offline_20261017T045618601569Z_4a72d48b/runtime_guard_verification.json

### CLI actually executed

- slow_entry simulate=True: exit=0, events=1, unavailable=0/15; output /mnt/c/Users/LEGION/Pbl4/debug/alert_diagnostics/v4/phase_e/runs/offline_20261017T045643560135Z_6f91104a
- polygon_slow_entry simulate=True: exit=0, events=1, unavailable=0/15; output /mnt/c/Users/LEGION/Pbl4/debug/alert_diagnostics/v4/phase_e/runs/offline_20261017T045646357802Z_603770a8
- slow_entry simulate=False: exit=0, events=0, unavailable=15/15; output /mnt/c/Users/LEGION/Pbl4/debug/alert_diagnostics/v4/phase_e/runs/offline_20261017T045648808550Z_dd774ac7

### Selected SHA-256

- src/realtime_worker_integrated_v3.py: 2fedb97b799214b18cfff9799286a6f5be5432ac2f61cfad60ec69b1466c2272
- debug/alert_diagnostics/v4/phase_d/pipeline_d.py: 8fd7286e7b8e0f4114a83f1bca70f60ac001317be324926fa363bc2e2a138a03
- debug/alert_diagnostics/v4/phase_d/tracking_d.py: a2b50108046a26e04beea20676390b398699749bd8ea2f37cf4db3ab47d585d3
- models/combined_data_model.pth: c03f38a947d426b39b7538a5478f823799d98b34e0fb299ec35a6520342a342a
