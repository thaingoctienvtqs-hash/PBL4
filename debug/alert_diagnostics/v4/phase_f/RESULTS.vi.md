# Phase F — kết quả Robust Tracking Recovery offline

## Kết luận

Đã triển khai prototype riêng và chạy kiểm thử/replay. **Chưa đạt toàn bộ yêu cầu an toàn recovery.** Hai gate cũ PASS khi bật geometry trial; mặc định bảo thủ không bật recovery thiếu bằng chứng danh tính và vẫn bỏ lỡ hai ca đó.

Geometry trial còn một phản ví dụ ALERT giả khi tay B không thể phân biệt bằng dữ liệu bbox/score với tay A. Gate giữ FAIL; không skip, expectedFailure hoặc sửa kỳ vọng để làm xanh. Không đưa F vào sản phẩm.

## Thực thi và regression

Môi trường thực tế: Ubuntu WSL, Conda contacthands, Python 3.7.16. Chỉ logic và JSONL; không Camera/GPU inference.

| Suite | PASS | FAIL | ERROR |
|---|---:|---:|---:|
| Frozen B/C (103) | 98 | 5 | 0 |
| Frozen D (64) | 64 | 0 | 0 |
| Frozen E in-memory (78) | 76 | 2 | 0 |
| F main (65) | 64 | 1 | 0 |
| F additional (6) | 6 | 0 | 0 |
| Tổng test duy nhất (316) | 308 | 8 | 0 |

B/C và E vẫn có đúng FAIL cũ. D 64/64 PASS; không sửa source/tests cũ. Bốn E file tests NOT RERUN vì chúng tạo artifacts trong E đang được bảo vệ; chạy sáu F file contracts tương đương thay thế.

Lệnh main thực chạy:
```bash
cd /mnt/c/Users/LEGION/Pbl4
/home/legion/miniconda3/envs/contacthands/bin/python -B -m debug.alert_diagnostics.v4.phase_f.run_checks
```
Exit 1, đúng vì gate identity còn FAIL.

Test additional đã chạy dưới runtime_guard và chạy lại bằng lệnh dưới, exit 0, 6/6 PASS:
```bash
/home/legion/miniconda3/envs/contacthands/bin/python -B -m unittest -v debug.alert_diagnostics.v4.phase_f.test_additional_f
```

Lượt preflight 1: 59 test, 57 PASS/2 FAIL. Một FAIL thiếu phát hiện candidate cạnh tranh gần nhau; đã bổ sung pre-ambiguity check, giữ test nguyên. FAIL còn lại là identity information limit. Preflight 2: 65 test, 64 PASS/1 FAIL, khớp lượt chính thức. Giữ build_inputs_01/02 và cả hai preflight reports.

## Hai quality gates E

Cùng bbox/scores/frame time và timeout, F không dùng oracle labels để matching:

| Ca | D event | E event | F geometry event | F strict event |
|---|---:|---:|---:|---:|
| missing ngay sau entry | 0 | 0 | 1 | 0 |
| frame_error ngay sau entry | 0 | 0 | 1 | 0 |

F geometry giữ ID 0 và entry episode 1, phát ALERT ~1.2s sau ba quan sát fresh .8/1.0/1.2. Hai frame probation không cộng positive_frames/ALERT; frame thiếu .6 không được tính. Contact history cũ bị bỏ, ba mẫu fresh mới đạt support .4s.

Đây là PASS của **mode thử nghiệm opt-in**, không phải PASS của mặc định bảo thủ hoặc bằng chứng chắc chắn cùng bàn tay trên ảnh thật.

## So sánh và oracle

48 kịch bản (31 E +17 F) x timeout 1/2/3 =144 rows. Mỗi mode nhận cùng JSONL và timeout; D/E core mismatches=0. Lưu đầy đủ input/settings/hash/replay trong run chính.

Trong 17 F cases tại timeout 2s, có 10 truth contact events theo oracle kiểm soát. Event được chấm theo actor của detection hiện tại và khoảng thời gian oracle, một truth ghép tối đa một event. Không đưa oracle vào matcher.

| Mode | TP kiểm soát | FP kiểm soát | FN kiểm soát | ID chỉ thuộc 1 actor | ID bị dùng cho nhiều actor |
|---|---:|---:|---:|---:|---:|
| D | 1 | 1 | 9 | 40 | 1 |
| E | 1 | 1 | 9 | 40 | 1 |
| F_geometry | 5 | 1 | 5 | 25 | 1 |
| F_strict | 0 | 0 | 10 | 34 | 0 |

Số single-owner ID không phải số bàn tay hoặc accuracy: nhiều ID có thể là fragmentation của cùng actor. Báo cả track_owner_transfers, actor_id_changes và confirmed_identity (bỏ proposal tentative) trong comparison.json.

F geometry có **7 lần commit recovery đúng actor, 1 sai, 0 không có oracle** trong nhóm 17 ca/timeout2. ID tentative được gắn cờ, không coi là danh tính đã xác nhận. Ca commit sai cũng bị tính là ID shared và FP, không được che bằng cách chỉ đếm số ID.

## Phát hiện theo kịch bản

- Hai gate cũ, multiple missing detection và đổi tốc độ/hướng nhỏ: F geometry khôi phục, D/E bỏ lỡ.
- Explicit missing ba frame và explicit frame_error ba frame: các test additional đều PASS, positive chỉ từ ba frame phục hồi.
- Multiple missing: timeout 1s không phục hồi quá hạn; 2s và 3s phục hồi. Không chọn 3s là tối ưu; recovery window vẫn cap 1.5s.
- Tay B gần vị trí vận tốc dự đoán: D/E ghép nhầm ID/entry, FP=1; F từ chối bằng anchor IoU/uniqueness, FP=0.
- Tay B bbox/shape giống hệt tại vị trí cũ: D/E không ALERT ca này; F geometry ghép nhầm và FP=1. Đây là **regression về FP của mode geometry**, không né tránh.
- Unsupported large motion: D/E giữ đúng ID và TP=1; F gate anchor overlap từ chối, FN=1. Đây là tổn thất Recall có thật trong dữ liệu kiểm soát.
- Crossing sau missing, nhiều candidate, bbox scale đổi: không chuyển entry/history sang candidate được xác định là mơ hồ.
- Camera MOVING/UNKNOWN hoặc calibration reference đổi: xóa pending/entry; không khôi phục trên view chưa tin cậy.
- Tay in sẵn không có entry: không ALERT.
- Recovery đúng ID nhưng OC=.149: không ALERT; hiện tại OC thấp cũng không được phát ALERT hồi tố từ hai high samples trước đó.
- Duplicate/non-increasing/NaN timestamp: không thêm mẫu; invalid payload ngắt state. Disconnect vẫn clear pending khi cache đầy hoặc frame ID trùng.
- Mất tiếp một frame trong probation: bỏ các mẫu chưa commit; không nối contact qua khoảng trống.
- Track đã ALERT trước missing: phục hồi không sinh event trùng cùng episode.

Ground truth là oracle **kịch bản kiểm soát**, không phải nhãn video thật. Các số TP/FP/FN/ID trên không thể dùng làm model Accuracy/Precision/Recall/F1.

## Đánh đổi và điều chưa thể xác nhận

Geometry trial tăng số TP từ 1 lên 5 trong nhóm thử này nhưng vẫn có 1 FP, ở phản ví dụ khác baseline; không thể tuyên bố ưu việt toàn diện. Strict giảm FP ở nhóm này về 0 nhưng bỏ lỡ cả 10 truth contact events. Không dùng việc ít ALERT để khẳng định Precision thực tế tốt hơn.

identity_observability.json là kiểm chứng độc lập:
- cùng observable input hash ở thế giới A còn đó và B thay thế A;
- khác oracle/ground truth, oracle không được matcher đọc;
- geometry trả 1 event trong cả hai, strict trả 0 cả hai.

Vì observable input giống hệt, không có luật chỉ dựa vào bbox/score/time có thể trả đúng cả hai. Cần thêm thông tin từ ảnh/appearance hoặc bằng chứng danh tính độc lập. Không sửa test bằng cách cho matcher đọc oracle hoặc đánh dấu B là không hợp lệ chỉ vì biết trước nhãn.

Mặc định geometry_recovery=False. Không tự bật trial khi ContactHands live. Chưa có appearance extractor/re-ID đã xác minh, chưa có dữ liệu crop/video độc lập có nhãn danh tính. Còn giữ FAIL này để ngăn coi prototype đã đủ an toàn.

## Cơ chế và giới hạn kỹ thuật

- Reuse TrackerD global assignment và ambiguity; chọn stationary/velocity hypothesis theo anchor IoU, centre, bbox shape, time uncertainty.
- D reacquire gate vẫn .1, không nới distance để ép test. Loose negative control .3 + bỏ gates có FP, test chứng minh F từ chối được ca đó.
- Ba quan sát mới trước commit; không kéo dài lifetime identity bằng tentative observations. Window=min(1.5,ID timeout) đo từ last confirmed.
- ROIEntry và TemporalD gốc được bọc defer; giữ cooldown/emitted_episode, không mang history cũ, replay buffered fresh frames một lần theo timestamp.
- Ngưỡng hand=.7, OC=.15, fast=.85, overlap=.3 không đổi.
- Recovery ba mẫu/window1.5s có thể không đủ ở 1 FPS/inference chậm; cần đánh giá nhịp thực. Temporal D vẫn theo thời gian, recovery chưa bất biến FPS.
- Hình học 2D không chứng minh tiếp xúc hoặc danh tính. Camera stability chỉ là mocked signals trong các test; không có extractor ảnh thật.
- Strict chỉ áp dụng khi có mất dấu được quan sát/gửi record missing. Không giải quyết thay thế bàn tay không quan sát được giữa hai frame liên tục.
- Generic E log reason khi probation có thể nói explicit_offline_stable; state RECOVERY_PENDING và track state_reason mới giải thích lý do ngừng xác nhận. Đọc recovery_evidence_frame_ids để thấy các frame được commit trễ.
- private D hooks/callback composition cần API ổn định hóa trước tích hợp; chưa benchmark CPU/GPU latency/VRAM.

## Bảo vệ và dữ liệu

672 file trong manifest bảo vệ (source sản phẩm/v3/v4/C/D/E, artifacts C/D/E, checkpoint và các tracked changes hiện có) giữ SHA-256 trước/sau. Không ghi ngoài F. Runtime guard main/additional: 0 blocked operation attempts, không gọi DB/network hoặc delete/rename.

Git status trước/sau khớp; git diff --check exit 0. Warning LF/CRLF của src/services/alert.py có sẵn, file không đổi hash. Các thay đổi web từ trước được giữ nguyên. Debug/ đã untracked nên Git status không hiển thị riêng F; final_verification có manifest.

Hash scope là các file được liệt kê, không phải checksum toàn dataset/SQL Server. Không sửa dataset/checkpoint/môi trường, repo ContactHands gốc bên ngoài, frontend hoặc DB. Không camera/GPU/train/commit/push.

## Files mới

Source: __init__.py, recovery_tracker.py, pipeline_f.py, cases_f.py, compare_f.py, replay_f.py, run_checks.py, test_f.py, test_io_f.py, test_additional_f.py.
Docs: README.vi.md, RESULTS.vi.md.
Artifacts: protected_before.json, build_inputs_01/02, preflight_01/02.json, additional_test_results.json, identity_observability.json, fixtures/, io_tests/, runs/, final_verification.json.
Không ghi đè file có sẵn hoặc artifacts cũ.

## Trạng thái cuối

- PASS: implementation/replay offline, hai gate cũ trong geometry trial, các safeguards có dữ liệu phân biệt.
- FAIL: gate không chuyển danh tính trong ca replacement bất khả phân biệt ở geometry mode.
- NOT TESTED: ảnh/video thật, camera, GPU inference, appearance re-ID, latency thực, model metrics.
- Thiếu thông tin: bằng chứng danh tính từ ảnh/crop để giải quyết tradeoff; không bị chặn do quyền cài đặt/chạy lệnh.

Accuracy >80%, Precision/Recall/F1 >=80%: **CHƯA ĐÁNH GIÁ**. Dừng tại Phase F offline, chờ duyệt bước bổ sung identity evidence/video offline có nhãn. Không tự chuyển sang camera/GPU hoặc website.

### Full controlled per-case TP/FP/FN

| Scenario | D | E | F geometry | F strict |
|---|---|---|---|---|
| explicit_missing_frame | 0/0/1 | 0/0/1 | 1/0/0 | 0/0/1 |
| explicit_frame_error | 0/0/1 | 0/0/1 | 1/0/0 | 0/0/1 |
| multiple_missing | 0/0/1 | 0/0/1 | 1/0/0 | 0/0/1 |
| speed_direction_change | 0/0/1 | 0/0/1 | 1/0/0 | 0/0/1 |
| unsupported_large_motion | 1/0/0 | 1/0/0 | 0/0/1 | 0/0/1 |
| replacement_near_prediction | 0/1/0 | 0/1/0 | 0/0/0 | 0/0/0 |
| replacement_indistinguishable | 0/0/0 | 0/0/0 | 0/1/0 | 0/0/0 |
| replacement_scale_change | 0/0/0 | 0/0/0 | 0/0/0 | 0/0/0 |
| recovered_low_contact_score | 0/0/0 | 0/0/0 | 0/0/0 | 0/0/0 |
| recover_current_score_invalid | 0/0/0 | 0/0/0 | 0/0/0 | 0/0/0 |
| timeout_expired | 0/0/1 | 0/0/1 | 0/0/1 | 0/0/1 |
| camera_shake | 0/0/1 | 0/0/1 | 0/0/1 | 0/0/1 |
| camera_unknown | 0/0/1 | 0/0/1 | 0/0/1 | 0/0/1 |
| printed_static | 0/0/0 | 0/0/0 | 0/0/0 | 0/0/0 |
| duplicate_and_bad_timestamp | 0/0/1 | 0/0/1 | 1/0/0 | 0/0/1 |
| crossing_after_missing | 0/0/1 | 0/0/1 | 0/0/1 | 0/0/1 |
| two_candidates_after_gap | 0/0/0 | 0/0/0 | 0/0/0 | 0/0/0 |

### Actual artifacts

- runs/offline_20261017T052908835196Z_541330a2
- additional_test_results.json
- identity_observability.json
- CLI explicit_missing_frame geometry=True exit=0 events=1: /mnt/c/Users/LEGION/Pbl4/debug/alert_diagnostics/v4/phase_f/runs/offline_20261017T053114106579Z_b42af09f
- CLI explicit_missing_frame geometry=False exit=0 events=0: /mnt/c/Users/LEGION/Pbl4/debug/alert_diagnostics/v4/phase_f/runs/offline_20261017T053116361557Z_ed9dc63c
- CLI replacement_indistinguishable geometry=True exit=0 events=1: /mnt/c/Users/LEGION/Pbl4/debug/alert_diagnostics/v4/phase_f/runs/offline_20261017T053118455734Z_d4845940

### Selected protected SHA-256

- src/realtime_worker_integrated_v3.py: 2fedb97b799214b18cfff9799286a6f5be5432ac2f61cfad60ec69b1466c2272
- debug/alert_diagnostics/v4/phase_d/tracking_d.py: a2b50108046a26e04beea20676390b398699749bd8ea2f37cf4db3ab47d585d3
- debug/alert_diagnostics/v4/phase_e/offline_pipeline.py: ff35cfbe76c7f1649d809bddc2ab87b0235f52c46cc7df757aac1bedbef17d7d
- models/combined_data_model.pth: c03f38a947d426b39b7538a5478f823799d98b34e0fb299ec35a6520342a342a
