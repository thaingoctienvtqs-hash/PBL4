# Kiến trúc runtime và API

```text
ESP32-CAM /capture
       │ HTTP JPEG
       ▼
esp32cam_capture.py (Windows) ── atomic replace ──> data/camera_frame.jpg
                                                        │
                                                        ▼
                                      src/realtime_worker.py (WSL)
                                      ContactHands two-stream model
                                      hand boxes + four contact scores
                                      ROI overlap + configured thresholds
                                          │            │
                             latest annotated JPEG    SQLite
                                          │            │
                                          └──── FastAPI dashboard
```

Worker cũng có thể lấy `/capture` trực tiếp hoặc đọc ảnh/ảnh trong thư mục offline. Không cần khởi tạo camera khi chạy unit test.

## ROI và theo dõi tiếp xúc theo thời gian

- ROI chuẩn hóa theo frame, chuyển sang pixel trước khi đo tỷ lệ giao giữa bbox bàn tay và ROI.
- Worker theo dõi mọi detection, ghép track bằng IoU và khoảng cách tâm chuẩn hóa. ID sống qua mất detection ngắn; track hết hạn sau track_timeout_seconds.
- Mỗi track giữ bbox/tâm, tuổi, dịch chuyển chuẩn hóa, thời gian đứng yên, ROI overlap và lịch sử Object-Contact 5 frame. Đứng yên sau 2 giây chỉ là thông tin, không chặn cảnh báo.
- Cảnh báo cần track đi từ ngoài vào ROI và Object-Contact hợp lệ 3/5 frame, hoặc score cao qua ít nhất 2 frame liên tiếp. Self-Contact và Other-Person-Contact không tự tạo nghi vấn chạm tranh.
- Bàn tay đã có trong ROI từ lúc khởi động chỉ ở CANDIDATE. RGB/ContactHands không thể luôn phân biệt tay thật với hình bàn tay trong tranh; hiện không có liên kết người–tay.
- ALERT giữ nguyên khi contact evidence còn; clear khi tay ra ROI hoặc evidence mất quá clear_after_seconds, sau đó track vào cooldown. Một lần chạm liên tục tạo tối đa một event/evidence.
- Event lưu thời điểm bắt đầu, thời điểm cảnh báo, track ID, Object-Contact score, overlap, lý do, chuyển động và stationary duration. Đây là nghi vấn AI cần người xác minh.

State transitions:
NO_HAND -> OUTSIDE_ROI: phát hiện tay ngoài ROI
OUTSIDE_ROI -> CANDIDATE: có Object-Contact candidate trong ROI
CANDIDATE -> ALERT: ROI entry và 3/5 frame, hoặc 2 frame liên tiếp score cao
ALERT -> ALERT: evidence vẫn tồn tại
ALERT -> COOLDOWN: rời ROI hoặc evidence mất quá thời gian clear
COOLDOWN -> CANDIDATE: cooldown kết thúc và có evidence mới
NO_HAND -> CAMERA_DISCONNECTED: frame nguồn lỗi hoặc cũ
CAMERA_DISCONNECTED -> NO_HAND: frame đọc được trở lại và reset tracks
Worker cũng có ERROR và NEEDS_CONFIGURATION khi model/ROI chưa sẵn sàng.

Latency, false positives và misses chưa được đo trên video có nhãn. Các luật 3/5 và 2 frame là giá trị khởi đầu, không phải số liệu tối ưu.
## Cấu hình

`configs/pbl4.json` chứa ROI, ngưỡng, số frame xác nhận, cooldown, đường dẫn tương đối, thiết bị và dashboard. ROI mặc định tắt. Có thể thay path/config qua `PBL4_CONFIG`, `PBL4_CAPTURE_FRAME`, `PBL4_LATEST_FRAME`, `PBL4_EVENT_DB` và `PBL4_EVIDENCE_DIR`. Đặt URL camera qua `PBL4_CAMERA_URL`; biến môi trường không được trả về bởi API config.

Threshold mặc định là giá trị khởi tạo để thử. Không có đánh giá tập test thực tế trong repository này.

## Lưu trữ

SQLite dùng hai bảng:

- `runtime_status`: trạng thái mới nhất cùng `updated_at`.
- `events`: loại sự kiện, timestamp, trạng thái xử lý, JSON score/box và đường dẫn evidence.

`src/data/history.json` là log cũ, được đọc để hiển thị nhưng không bị migrate, truncate hoặc ghi đè. Dữ liệu mới đi vào SQLite; cooldown ở database giữ hiệu lực qua restart. Database/evidence là file runtime bị `.gitignore` bỏ qua.

## Cảm biến

`SensorAdapter` tách nguồn cảm biến khỏi model. Hiện chỉ có `UnconfiguredSensor` và `MockSensor`; cả hai đều không báo `available=true`. Chưa có loại cảm biến, giao thức, firmware hoặc kiểm thử phần cứng thật.



### Tinh chỉnh temporal

| Khóa cấu hình | Mặc định | Mục đích |
| --- | ---: | --- |
| history_window_frames | 5 | Cửa sổ contact gần nhất |
| minimum_contact_roi_frames | 3 | Số frame hợp lệ tối thiểu |
| fast_contact_score | 0.85 | Ngưỡng đường cảnh báo nhanh |
| fast_contact_consecutive_frames | 2 | Số frame liên tiếp ngưỡng cao |
| track_match_distance_normalized | 0.25 | Ghép tâm độc lập độ phân giải |
| movement_threshold_normalized | 0.015 | Lọc jitter và xác định ROI entry |
| track_iou_threshold | 0.1 | Ghép bbox khi tâm đổi |
| track_timeout_seconds | 1.0 | Giữ track khi mất detection |
| clear_after_seconds | 0.75 | Xóa ALERT sau khi evidence mất |
| cooldown_seconds | 60 | Chống lặp event cho cùng track |
| stationary_seconds | 2.0 | Chỉ là thông tin |

Tăng minimum_contact_roi_frames hoặc fast_contact_score để thận trọng hơn. Chỉ giảm ngưỡng sau khi xem video thật có nhãn; ROI cần hiệu chuẩn theo camera. move_threshold_pixels và confirm_frames được giữ để tương thích config cũ.
