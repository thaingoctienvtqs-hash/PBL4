# ArtGuard — Kiến trúc và trạng thái tích hợp

Ngày đối chiếu: 18/10/2026. Repository: `C:/Users/LEGION/Pbl4`.
Nhánh `test-web`, HEAD `aca33ee901bd12f527499c20222100b104d0d6b1`.
Tài liệu phản ánh source và hiện trạng kiểm kê; lượt này không chạy AI, camera, website hay truy vấn database.

## Cách đọc bằng chứng

- **SOURCE**: xác nhận được định nghĩa, import hoặc đường gọi trong source; chưa chứng minh runtime hoạt động.
- **ĐÃ BÁO CÁO**: nhóm đã chạy hoặc báo cáo cũ đã ghi nhận; không kiểm chứng lại trong lượt tài liệu hóa.
- **CHƯA XÁC MINH**: chưa có phép thử xuyên suốt trên hiện trạng này.
- **THỬ NGHIỆM**: logic/replay offline, không phải pipeline đã triển khai.

## Bối cảnh vật lý và mục tiêu

ESP32-CAM OV3660 gắn **trực tiếp sát mép trên khung tranh**, nhìn **xiên xuống dọc bề mặt tranh**. Đây là vị trí nhóm yêu cầu, chưa kiểm tra bằng camera trong lượt này. Góc nghiêng, FOV, độ phủ và vùng mù chưa đo; không giả định nhìn hết tranh. ROI phải hiệu chuẩn theo đúng ảnh nguồn, độ phân giải và phiên lắp camera.

Mục tiêu Accuracy >80%, hướng tới Precision/Recall/F1 ≥80% trên test độc lập có nhãn: **CHƯA ĐÁNH GIÁ**. Mong muốn contact→ALERT dưới 500 ms nếu đo thực tế cho phép; chưa có kết quả xác nhận. Object-Contact và overlap 2D chỉ cung cấp nghi vấn, không chứng minh khoảng cách vật lý hay TOUCH. Không hạ điều kiện an toàn để tăng số ALERT.

## Sơ đồ các nhánh đang cùng tồn tại

Đường liền: có đường gọi/cấu hình trong source. Đường nét đứt: handoff bên ngoài hoặc tích hợp chưa xác minh. Đường liền không đồng nghĩa đã chạy thành công ở lượt này.

~~~mermaid
flowchart TD
  CAM["ESP32-CAM OV3660 /capture"] -.-> WIN["Producer Windows: snapshot"]
  WIN -.-> FRAME["data/camera_frame.jpg"]
  FRAME --> V3["ContactHands worker v3: file-watch"]
  CAM --> V3
  CH["ContactHands 2 stream + checkpoint"] --> V3
  V3 --> ROI["geometry + tracking + contact_logic"]
  ROI --> LOCAL["SQLite riêng + preview + evidence"]
  LOCAL -. "chưa có bridge được xác minh" .-> API["FastAPI web/backend"]
  REACT["React/Vite ArtGuard"] --> API
  API --> SQL["SQL Server: alerts, evidence, metadata"]

  PRED["Prediction JSONL kiểm soát"] --> E["Phase E adapter"]
  E --> D["Phase D: stability, tracking, temporal"]
  E --> F["Phase F: recovery thử nghiệm"]
  F --> D
  D --> LOG["JSONL kết quả; không phải SQL Server"]

  SRC["Video / webcam / ESP32 stream"] --> YOLO["video_demo: YOLO + server.contact"]
  YOLO --> YOUT["MP4 / JSONL / evidence riêng"]
  YOUT -. "chưa tích hợp" .-> API

  LEG["start_pbl4.bat: luồng cũ"] --> OLD["src.app.realtime + src.app.api"]
  OLD --> HTML["index.html gốc + JSON/text lịch sử"]
~~~

## Đối chiếu từng đường kết nối

| Đường | Bằng chứng | Kết luận |
|---|---|---|
| ESP32 /capture → Windows snapshot → WSL | Nhóm báo cáo đã lưu ảnh và chạy file-watch; `data/camera_frame.jpg` có trên đĩa | ĐÃ BÁO CÁO; không thử thiết bị lần này |
| Snapshot → ContactHands → phân tích | [worker v3](../../src/realtime_worker_integrated_v3.py), dòng 164–330, 380–450 | SOURCE; nhóm đã báo cáo NO_HAND/NO_CONTACT/CANDIDATE |
| ContactHands 2 stream | [wrapper](../../src/core/contacthands_compat.py), dòng 15–35; [detect_compat](../../src/detect_compat.py), dòng 61–104 | SOURCE; khởi tạo có thể nạp model/cache và GPU |
| Track/temporal → SQLite/evidence | worker v3 dòng 308–329; [EventStore](../../src/services/event_store.py), dòng 13–53, 76–103 | SOURCE; tạo DB và ghi khi chạy, không được coi là SQL Server |
| React → FastAPI → SQL Server | [client](../../web/frontend/src/api/client.ts), dòng 3; [Vite proxy](../../web/frontend/vite.config.ts); [API](../../web/backend/app/main.py), dòng 42–54; [DB](../../web/backend/app/db.py), dòng 13–20 | SOURCE; kết nối SQL có báo cáo cũ, chưa thử end-to-end hiện tại |
| SQLite AI → SQL Server → website có ALERT AI thật | Không thấy bridge trong các entrypoint/đường gọi vừa đối chiếu; API tự mô tả mô phỏng ở main.py dòng 20 | CHƯA XÁC MINH; không suy diễn từ dữ liệu demo |
| D/E/F → log offline | [E](../../debug/alert_diagnostics/v4/phase_e/offline_pipeline.py), [F](../../debug/alert_diagnostics/v4/phase_f/pipeline_f.py) | THỬ NGHIỆM, chưa là worker v3 |
| YOLO → kết quả riêng | [video_demo](../../src/app/video_demo.py), dòng 32–99; [server.contact.video](../../server/contact/video.py) | SOURCE; không phải ContactHands |
| CameraLiveView → camera thật | [component](../../web/frontend/src/components/CameraLiveView.tsx), dòng 31–44, 137–151; không thấy caller trong cây React đã rà soát | CHƯA XÁC MINH, không mở consumer camera bổ sung |

## Biên dữ liệu cần giữ riêng

- ContactHands v3 mặc định dùng `src/data/events.sqlite3`, `src/data/latest.jpg`, `src/data/alerts`; cấu hình có thể override. Xem [cấu hình tương thích](../../src/utils/config_compat.py), dòng 31–36, 155–162, 192–197.
- Luồng cũ dùng status text/history JSON, không tự đọc SQLite của v3: [realtime cũ](../../src/app/realtime.py), [API cũ](../../src/app/api.py), [history](../../src/services/history.py).
- Website dùng SQLAlchemy/SQL Server; `app_env=testing` có SQLite memory riêng, không phải DB worker. [models](../../web/backend/app/models.py) có alerts/alert_notes/alert_history, evidences/evidence_media/evidence_history và bảng quản trị.
- Evidence ở worker là file cục bộ; website có API evidence riêng được đăng ký. Chưa xác minh upload, ánh xạ ID, quyền truy cập và chống trùng event giữa hai bên.
- Phase E/F dùng fixture và JSONL; stability mô phỏng không phải phép đo chuyển động camera. Schema thu thập v2 nằm ở [schema_v2](../../debug/alert_diagnostics/v4/appearance_preparation/schema_v2/README.vi.md); dữ liệu SYNTHETIC_TEST không chứng minh chất lượng AI.

## Điều kiện trước khi gọi là tích hợp hoàn chỉnh

Cần phiên thu thật được hiệu chuẩn, một nguồn camera chính, timestamp/sai số đồng bộ, nhãn TOUCH/NEAR_NO_TOUCH/NO_TOUCH/UNKNOWN, split theo phiên; đo event đúng/sai, coverage, UNKNOWN, false alerts/hour và latency capture→host→inference→decision→API. Chưa có phép đo này thì không kết luận đạt Accuracy hoặc 500 ms.

Xem [entrypoint](ENTRYPOINTS.vi.md), [môi trường](ENVIRONMENTS.vi.md), [phụ thuộc](DEPENDENCIES.vi.md) và [kế hoạch an toàn](SAFE_REFACTOR_PLAN.vi.md).
