# Kết quả Giai đoạn D — ContactHands ArtGuard

## Kết quả thực thi

Chạy thực tế trên Ubuntu WSL, Conda contacthands, Python 3.7.16. Chỉ chạy pure logic; không import Torch/Detectron2 để inference, không mở camera, không truy cập SQL Server.

Lệnh đã chạy:
```powershell
wsl -d Ubuntu-22.04 --cd /mnt/c/Users/LEGION/Pbl4 --exec /home/legion/miniconda3/envs/contacthands/bin/python -B -m debug.alert_diagnostics.v4.phase_d.run_tests
```

Exit code 0. Runner coi đúng 5 FAIL đã biết trên source v4 bất biến là bằng chứng baseline, không chuyển chúng thành PASS.

| Suite | PASS | FAIL | ERROR |
|---|---:|---:|---:|
| B/C frozen (103) | 98 | 5 | 0 |
| D (64) | 64 | 0 | 0 |
| Total (167) | 162 | 5 | 0 |

Artifacts: runs/logic_20261017T043316108807Z_e91819d3; comparison 25 scenarios x 3 timeouts = 75 rows.

## Năm quality gates

| Gate | Kết quả bản D | Phạm vi chứng minh |
|---|---|---|
| Tiếp xúc thường 30 FPS | PASS | 3/5 phiếu giữ nguyên; duration dùng timeline riêng |
| Fast path 30 FPS | PASS | score >=0.85; span >=0.2 giây không bị deque 5 cắt ngắn |
| Disconnect cache đầy | PASS | control đi trước data gate; xóa active/entry/history; CAMERA_OFFLINE |
| Hai tay giao nhau chuyển chủ ID | PASS trên ca kiểm soát | oracle ownership không chuyển; retire ID mơ hồ và xóa bằng chứng |
| Camera pan tay in sẵn | PASS cho cơ chế chặn bảo thủ; hình ảnh thật NOT TESTED | UNKNOWN/MOVING không xác nhận entry; không có extractor đã xác minh |

Không tuyên bố đã giải quyết toàn diện camera pan hoặc danh tính qua mọi che khuất. Nếu yêu cầu gate camera phải chứng minh bằng video thật, phần đó còn BLOCKED do chưa thu thập ảnh/video có nhãn và chưa được phép chạy camera/inference.

## Nguyên nhân và bản sửa

V4 cũ dùng cùng deque 5 cho vote, tổng thời gian hỗ trợ và chuỗi fast. Tối đa 4/FPS giây: tại 30 FPS chỉ 0.133 giây, dưới cả 0.4 và 0.2. Tại 20 FPS cũng không đạt 0.4 giây. D giữ vote 5 riêng, evidence tối đa tuổi 6 giây. Xóa khi mất detection, gap >2 giây hoặc đổi episode; không dùng thời gian thiếu detection để tăng hỗ trợ. Không sửa ngưỡng model.

V4 disconnect gọi data gate, nên cache đầy/ID trùng có thể bỏ lệnh xóa trạng thái. D control path không phụ thuộc các bộ lọc đó, nhưng kiểm tra session; reconnect phải rõ ràng và cần entry mới.

Tracking D dùng dự đoán chuyển động + ghép toàn cục, phát hiện vùng ghép mơ hồ và retire cả thành phần. Test kiểm tra actor-to-ID chứ không chỉ số ID, đảo thứ tự detection, đổi hướng, mất detection và lưới 24 biến thể speed/offset/missing. Không dùng nhãn oracle trong matcher.

Camera D chỉ có hợp đồng correspondence nền so mốc hiệu chuẩn và chính sách abstain mặc định; chưa có trích xuất feature ảnh. Các điểm trong test là giả lập, không phải dữ liệu camera. Provider trả sai vẫn có thể gây FP; đã có test lưu phản ví dụ đó, không che giấu.

## So sánh cùng prediction, timeout 2 giây

Số dưới đây là số event logic, không phải TP/FP vật lý. D controlled nhận thêm tín hiệu nền giả lập độc lập; D unknown không có tín hiệu thì không ra quyết định. Xem replays.json để kiểm tra đầy đủ input/context/output và hash prediction.

| Scenario | v3 | v4 | D controlled | D unknown |
|---|---:|---:|---:|---:|
| camera_fast_jolt_printed_hand | 1 | 1 | 0 | 0 |
| camera_slow_pan_printed_hand | 0 | 1 | 0 | 0 |
| depicted_static | 0 | 0 | 0 | 0 |
| fast_path | 1 | 1 | 1 | 0 |
| gap_1_01 | 1 | 1 | 1 | 0 |
| hands_cross_offset_0.0 | 1 | 1 | 0 | 0 |
| hands_cross_offset_0.01 | 1 | 1 | 0 | 0 |
| hands_cross_offset_0.03 | 1 | 1 | 0 | 0 |
| high_fps_20_moderate | 1 | 0 | 1 | 0 |
| high_fps_30_fast | 1 | 0 | 1 | 0 |
| high_fps_30_moderate | 1 | 0 | 1 | 0 |
| initial_inside | 0 | 0 | 0 | 0 |
| long_detection_loss | 0 | 0 | 0 | 0 |
| multiple_hands | 1 | 1 | 1 | 0 |
| normal_entry_hold | 1 | 1 | 1 | 0 |
| pass_by_low_score | 0 | 0 | 0 | 0 |
| pass_by_one_spike | 0 | 0 | 0 | 0 |
| repeated_detection_missing | 1 | 0 | 0 | 0 |
| score_oscillation | 1 | 0 | 0 | 0 |
| short_detection_loss | 1 | 1 | 1 | 0 |
| slow_entry | 0 | 1 | 1 | 0 |
| thin_border_overlap_035 | 1 | 0 | 0 | 0 |
| three_five_strong_oscillation | 1 | 0 | 0 | 0 |
| two_contact_bouts_same_roi | 2 | 1 | 1 | 0 |
| uneven_frames | 1 | 1 | 1 | 0 |

Crossing offset 0.0, owner transfers: v3=2, v4=2, D=0. D retires uncertain IDs; no claim of ID continuity.

## FPS và timeout

Test tiếp xúc kéo dài/score 0.6 và 0.85 chạy tại 1/5/10/15/30 FPS. Test ngắn <0.2 giây không ALERT; tiếp xúc thường 0.3 giây không ALERT; score 0.85 trong 0.3 giây tại 30 FPS đủ fast path. Đó là độ trễ logic trên timestamp kiểm soát, không phải latency camera/model.

Ở 1 FPS với 2 giây và 2 mẫu ROI, D không override điều kiện tối thiểu 3 phiếu. Test kéo dài dùng 3 giây cho mọi FPS. Không gọi cơ chế này hoàn toàn bất biến FPS về độ trễ: số phiếu và độ thưa quan sát vẫn là giới hạn thông tin.

Ca gap_1_01:
| Timeout ID | Số ID D | Số event D |
|---|---:|---:|
| 1 giây | 6 | 0 |
| 2 giây | 1 | 1 |
| 3 giây | 1 | 1 |

Không chọn 3 giây là tối ưu. Chưa có phân phối latency/frame gap thực tế để chọn timeout; tăng TTL cũng tăng nguy cơ ghép nhầm khi mất dấu.

## Regression và rủi ro còn lại

- Bộ B/C bất biến giữ đúng 98 PASS và 5 FAIL cũ, không xuất hiện thêm lỗi baseline. Không chạy toàn bộ characterization C lên D rồi yêu cầu những test chứng minh bug cũ vẫn đúng.
- Các ca không mơ hồ: entry chậm, entry rồi giữ yên, nhiều tay độc lập, ngưỡng score, timestamp, dropout, ROI change được kiểm tra lại trong D. Một entry kéo dài chỉ sinh một event.
- **Recall có thể giảm:** 3 ca crossing vốn v4 sinh 1 event, D sinh 0 do retire ID/entry; không coi đây là cải thiện accuracy. Unknown camera cũng không phát hiện tiếp xúc, cần ghi tỷ lệ unavailable.
- Tay thật xuất hiện sẵn trong ROI không được tự xác nhận, giống chủ đích chống tay in sẵn. Không thể kết luận đó là không tiếp xúc.
- Hai đợt chạm thật trong cùng entry episode vẫn gộp 1 event (v3:2, v4:1, D:1); đây là giới hạn đã biết, chưa mở rộng episode semantics.
- Ngưỡng proximity 0.08 có thể bỏ nhầm hai tay độc lập ở gần nhau; không có appearance/re-ID thật. Đổi hướng mạnh/chuyển động không quan sát được vẫn chưa bảo đảm đúng danh tính.
- Nới timeline ra 6 giây có thể tích lũy hỗ trợ từ các đoạn score hợp lệ rời rạc; cần đo false positive trên video. Missing observation ngắt bằng chứng hoàn toàn, có thể giảm Recall.
- Camera provider là phụ thuộc tin cậy; không có kiểm chứng ảnh, chuyển động nền chưa được giải quyết thực tế. UNKNOWN không được tính như TN trong metric.
- Adapter tương lai phải gửi disconnect khi capture timeout; module không có timer nền. Khi đầy cache cần rollover session có chủ đích. Không tái sử dụng trạng thái cũ khi decision_available=false.
- Chưa benchmark độ trễ CPU/GPU hoặc VRAM; không thay đổi ContactHands model.
- Chưa tích hợp sản phẩm. Không tự chạy worker mới/camera/GPU hoặc chuyển sang website.

## Preflight trung thực

preflight_01: 59 test, 1 FAIL, 2 ERROR. Hai ERROR do test giả định ID=1 trong khi tracker bắt đầu từ 0; FAIL do chỉ có 2 mẫu tại 1 FPS nhưng mong đủ 3 phiếu. Đã giữ nguyên build_inputs_01 và traceback.

preflight_02: 60/60 PASS. Test dùng ID thực, ca kéo dài 3 giây; bổ sung explicit test 2 mẫu không ALERT. preflight_03 và lượt chính thức: 64/64 PASS, thêm lưới crossing, phản ví dụ stability sai và các giới hạn episode. Không sửa logic sản phẩm hoặc test B/C để đổi FAIL thành PASS.

## Bảo vệ dữ liệu và file

Toàn bộ mã và artifacts mới nằm dưới phase_d/. Các đường dẫn source được kiểm tra trước và mở chế độ x, không ghi đè. Các lần preflight và run đều giữ riêng.

Snapshot mở rộng gồm 281 file hiện có: tracked files, source/config/test và 90 file bảo vệ ban đầu gồm v3, contact_logic, v4/C, checkpoint, hai file web vốn đang thay đổi. Tất cả hash khớp trước/sau test. Đây là hash file trong phạm vi snapshot, **không phải kiểm tra checksum toàn dataset/database**; không mở/sửa dữ liệu đó.

git diff --check exit 0; Git cảnh báo LF sẽ được đổi CRLF trong src/services/alert.py nếu Git ghi sau này. Audit không đổi file đó. Git status trước/sau giữ nguyên hai tracked modifications web/.env.example và web/frontend/package-lock.json cùng các file untracked đã có; debug/ đã untracked từ trước.

Cú pháp 9 file Python D được parse trực tiếp bằng Python 3.7, JSON parse thành công. Không ghi bytecode từ lượt chạy -B.

Xem final_verification.json và runs/.../protected_after.json để lấy toàn bộ SHA-256 và xác minh Git cuối lượt.

## Đánh giá AI độc lập

Accuracy >80%, Precision/Recall/F1 >=80%: **CHƯA ĐÁNH GIÁ**. Chưa có video thật có nhãn độc lập cho D; không dùng 64 unit test làm accuracy. Dừng tại Phase D, chờ duyệt trước camera/GPU hay tích hợp.

### SHA-256 selected protected files

- src/realtime_worker_integrated_v3.py: 2fedb97b799214b18cfff9799286a6f5be5432ac2f61cfad60ec69b1466c2272
- src/core/contact_logic.py: a2790ae68cc44d89c21c95a2db2f88e4ecbe121fd6b1229b93b82eb67f63e1e7
- debug/alert_diagnostics/v4/pipeline_v4.py: cc4e305d9b6d3f801d1e10533c69049eaf01d1f47035e42ad874bb5c034ed691
- debug/alert_diagnostics/v4/temporal_v4.py: 449db76a25d914281519b6500fba6ebb94e627b1a06a6a57873d866a142c83e1
- models/combined_data_model.pth: c03f38a947d426b39b7538a5478f823799d98b34e0fb299ec35a6520342a342a
