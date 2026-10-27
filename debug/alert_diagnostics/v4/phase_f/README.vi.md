# Phase F — Robust Tracking Recovery, offline

## Kết luận và hai chế độ

Đây là bản thử nghiệm mới, không thay sản phẩm/v3/v4/C/D/E. Hai quality gates E được khắc phục **trong chế độ geometry opt-in**. Còn một quality gate false positive về danh tính không phân biệt được: FAIL thật, không skip/expectedFailure.

Mặc định `geometry_recovery=False`: từ chối khôi phục ID từ bbox sau mất dấu nếu thiếu bằng chứng danh tính. Không có appearance provider trong giai đoạn này; chế độ mặc định cũng bỏ lỡ hai ca phục hồi E. Không tuyên bố giải quyết trọn vẹn mục tiêu vừa tăng Recall vừa bảo đảm không chuyển entry sang tay khác.

Opt-in `geometry_recovery=True`: phục hồi hình học có probation, chỉ để so sánh offline. Không đủ điều kiện bật ngoài thực tế vì phản ví dụ đã ghi nhận.

## Thiết kế

### Phân tích phương án

1. Chỉ tăng reacquire_distance: loại. Negative control nới lên 0.3 và bỏ IoU/shape cho tay B nhận episode của A, sinh ALERT giả.
2. Constant velocity của D: giữ làm một giả thuyết, nhưng không dùng đơn độc. Ca E tay đã dừng bị dự đoán x=.575 thay vì .45, sai lệch .125 > gate .1.
3. Stationary + constant velocity với uncertainty theo gap: triển khai. Không nới gate D .1.
4. Short-window re-identification: mới là **spatial reassociation**, không phải appearance re-ID. Dữ liệu bbox/score không đủ chứng minh danh tính; cần crop/features và đánh giá độc lập sau.

### RecoveryTracker

Tái sử dụng assignment, proximity/ambiguity và normal tracking của TrackerD. Tính recovery candidates trước ghép; chỉ có một candidate tương thích và không có track/detection cạnh tranh mới được đưa vào probation.

Bộ tham số thử nghiệm (chưa tối ưu trên ảnh thật):
- window=min(1.5s, max_idle_seconds), đo từ lần quan sát danh tính đã xác nhận cuối cùng;
- width/height ratio trong [0.85,1.15];
- stationary hypothesis: anchor IoU >=0.75, center distance <=0.025;
- motion hypothesis: anchor IoU >=0.4, predicted IoU >=0.6, distance <=min(reacquire_distance,0.02+0.08*gap);
- giới hạn di chuyển/IoU giữa các quan sát probation, cùng cơ chế phát hiện ambiguity của D.

Uncertainty là heuristic đẳng hướng có giới hạn, không phải covariance đã hiệu chuẩn/Kalman hoặc xác suất danh tính. Không dùng Object-Contact score làm đặc trưng nhận dạng tay.

Ba quan sát phục hồi mới, tăng timestamp nghiêm ngặt, mới được commit. Quan sát tentative không kéo dài tuổi ID gốc; vượt window/timeout => retire. Missing tiếp trong probation hủy mẫu tentative. Camera MOVING/UNKNOWN, disconnect hoặc input barrier xóa toàn bộ pending state.

Candidate_parent ID trong probation được log bằng track_id và track_id_is_tentative=true; không quảng bá đó là danh tính chắc chắn. Báo cáo oracle đếm cả proposal và assignment đã commit, không che ghép nhầm bằng cách chỉ đếm số ID.

### ROI episode và contact history

PipelineF giữ ROIEntry/TemporalD gốc, bọc thêm defer:
- Trong probation, entry chưa được cấp cho candidate; positive_frames=0, không ALERT.
- Buffer chỉ lưu quan sát mới thật từ JSONL, tối đa 3 trong cửa sổ. Missing không được buffer như tiếp xúc.
- Khi commit hình học, phát lại các quan sát đó **một lần, theo timestamp gốc** vào ROIEntry/TemporalD mới. History tiếp xúc trước gap không được mang sang; giữ lifecycle cooldown/emitted_episode để không nhân đôi event.
- Nếu frame hiện tại score không hợp lệ, không phát ALERT hồi tố từ hai mẫu high trước đó.
- D vẫn yêu cầu 3/5 và support >=0.4s, hoặc fast score >=0.85, span >=0.2s; giữ hand=.7, OC=.15, overlap=.3.

Recovery buffering khiến frame trước đó chưa được dùng lúc nhận nhưng có thể được dùng sau commit; log recovery_evidence_frame_ids và recovery_first_confirmation_timestamp giải thích. used_for_confirmation trong adapter E là chỉ số tại thời điểm trả frame, không phải tổng số mẫu được commit về sau. Generic reason có thể là explicit_offline_stable khi state=RECOVERY_PENDING; xem state_reason của track để biết vì sao chưa xác nhận.

Khôi phục geometry không phải bằng chứng vật lý cùng tay. Sau commit vẫn có residual false positive, không được dùng nó làm producer đáng tin cậy cho sản phẩm.

## Tái lập trên Ubuntu WSL/Python 3.7.16

```bash
cd /mnt/c/Users/LEGION/Pbl4
/home/legion/miniconda3/envs/contacthands/bin/python -B -m debug.alert_diagnostics.v4.phase_f.run_checks
```

Đã chạy: exit 1 do information-limit gate chưa đạt. Kết quả chính F 65 test: 64 PASS/1 FAIL/0 ERROR. Frozen B/C, D và E in-memory chạy lại; giữ FAIL cũ. Bốn E I/O tests không chạy lại vì chúng ghi vào E; thay bằng sáu file tests F.

Sáu test thêm đã chạy riêng qua run_suite dưới runtime_guard, 6/6 PASS; tái lập:
```bash
/home/legion/miniconda3/envs/contacthands/bin/python -B -m unittest -v debug.alert_diagnostics.v4.phase_f.test_additional_f
```

Tổng test F duy nhất: 71, 70 PASS/1 FAIL. Runner chính không tự load module additional, nên chạy cả hai lệnh trên. Không cộng các lần lặp test thành test mới.

### Replay hai quality gates

```bash
/home/legion/miniconda3/envs/contacthands/bin/python -B -m debug.alert_diagnostics.v4.phase_f.replay_f \
  --input debug/alert_diagnostics/v4/phase_f/fixtures/explicit_missing_frame.jsonl \
  --config debug/alert_diagnostics/v4/phase_f/fixtures/timeout2.settings.json \
  --simulate-stability --geometry-recovery
```

Đã chạy: 1 event, ID 0/episode 1, tại ~1.2s. Đổi explicit_missing_frame thành explicit_frame_error để chạy ca lỗi frame. Có config timeout1/2/3 riêng; không sửa config sản phẩm.

Bỏ geometry-recovery: 0 event trên cùng input, mặc định bảo thủ. Bỏ simulate-stability: provider mặc định UNKNOWN, không coi camera ổn định.

Thay input bằng replacement_indistinguishable.jsonl: geometry sinh 1 ALERT giả theo oracle. CLI exit 0 chỉ biểu thị input hợp lệ, không chứng nhận quality/identity. Dùng run_checks và truth_controlled.json để chấm cảnh báo.

## Đánh giá và so sánh

compare_f.py dùng cùng JSONL, ROI, stability signal và timeout 1/2/3 cho D, E, F geometry và F strict. 48 scenarios x 3 =144 rows; 31 E scenarios và 17 F oracle scenarios. Lưu input SHA-256, config, full replay và comparison.json.

Đếm event theo actor của detection hiện tại và khoảng thời gian oracle, mỗi truth event ghép tối đa một ALERT. wrong/shared ID là ID đã gán cho hơn một actor; nhiều single-owner IDs có thể là fragmentation, không phải tốt hơn.

Ground truth ở đây chỉ là kỳ vọng kịch bản kiểm soát. Không phải nhãn video, không quy đổi thành độ chính xác model. Xem RESULTS.vi.md để có TP/FP/FN, ID, recovery commit và từng ca.

## Không đủ thông tin về danh tính

identity_observability.json chứa hai thế giới:
- tay A còn đó, bắt đầu tiếp xúc trong gap;
- tay A đi mất, B cùng bbox xuất hiện, không chạm.

Bỏ oracle metadata (matcher không đọc), toàn bộ bbox/scores/timestamps/stability input giống hệt, SHA-256 giống nhau. Geometry trả 1 event trong cả hai; strict trả 0 cả hai. Không có luật dựa chỉ vào các input này vừa khôi phục ca A vừa từ chối ca B.

Hướng tiếp theo cần dữ liệu ảnh/crop có nhãn danh tính để thử appearance, kích thước/pose chi tiết và motion background/occlusion cues. Chưa có extractor hoặc benchmark appearance thật. Cũng không được giả định appearance luôn phân biệt được hai tay giống nhau.

## Giới hạn

- Recovery ba quan sát trong <=1.5s có thể bỏ lỡ khi inference chậm/1 FPS. Temporal D theo thời gian vẫn giữ nguyên; recovery chưa bất biến FPS.
- Tăng timeout từ 2 lên 3 không mặc nhiên giúp vì recovery window cap 1.5; chưa tối ưu trên latency thực.
- Gate anchor IoU có thể bỏ tay thật di chuyển nhanh: unsupported_large_motion D/E đúng, F bỏ lỡ.
- Crossing/ambiguity, camera unknown/moving, thay calibration, inside-at-first đều xử lý bảo thủ, giảm Recall.
- 2D Object-Contact + ROI không chứng minh tay chạm mặt tranh.
- Replay lưu log trong RAM; chưa benchmark hiệu năng thực. Không watchdog/camera capture loop.
- D/E module private hooks/factories được dùng qua composition, cần chuẩn hóa API trước tích hợp sản phẩm.

Accuracy >80%, Precision/Recall/F1 >=80% trên video độc lập: **CHƯA ĐÁNH GIÁ**. Không dùng unit test hoặc các số controlled TP/FP/FN để tuyên bố đạt.

Mọi source/artifact mới nằm trong F. Hash trước/sau của 672 file được bảo vệ và manifest mới trong final_verification.json. Không sửa dataset/checkpoint/môi trường/DB/frontend; không camera/GPU, commit/push. Dừng chờ duyệt.
