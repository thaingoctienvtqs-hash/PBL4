# ArtGuard — Bản đồ phụ thuộc cần bảo vệ

Đối chiếu tĩnh ngày 18/10/2026. Mũi tên biểu diễn import/đường gọi có trong source, không thay thế kiểm tra runtime. Không import module dự án trong Nhóm 1.

## Worker v3

~~~mermaid
flowchart TD
  V3["realtime_worker_integrated_v3"] --> CFG["utils.config_compat"]
  V3 --> G["core.geometry"]
  V3 --> CL["core.contact_logic"]
  V3 --> CAM["services.camera_compat"]
  V3 --> DB["services.event_store: SQLite"]
  V3 --> SENSOR["services.sensors.UnconfiguredSensor"]
  V3 -. "lazy import _load_detector" .-> WRAP["core.contacthands_compat"]
  WRAP --> DET["detect_compat qua src trên sys.path"]
  DET --> PKG["contact_hands_two_stream"]
  DET --> DATA["datasets: đăng ký ContactHands_*"]
  PKG --> REG["Detectron2 registry / CustomPredictor"]
  REG --> YAML["ContactHands.yaml / second_stream.yaml / _BASE_"]
  YAML --> W["checkpoint stream 1 + stream 2/cache"]
~~~

| Phụ thuộc | File/dòng và hợp đồng |
|---|---|
| Nhập baseline | [worker v3](../../src/realtime_worker_integrated_v3.py), dòng 10–16; không đổi tên module vì diagnostics import nó |
| Prediction | v3 dòng 28–35 lấy `pred_boxes`, `scores`, `pred_cats`; [wrapper](../../src/core/contacthands_compat.py), dòng 32–36 trả instances; worker đọc các field bằng .tolist(), không có lệnh .to("cpu") tường minh ở hàm này |
| Geometry / temporal | [geometry](../../src/core/geometry.py), [contact_logic](../../src/core/contact_logic.py), dòng 9, 89; overlap không chứng minh TOUCH vật lý |
| Camera I/O | [camera_compat](../../src/services/camera_compat.py), dòng 15–61: fetch JPEG, ghi nguyên tử; không thay bằng camera.py cũ chỉ có Camera |
| Persistence | [EventStore](../../src/services/event_store.py), dòng 13–53 khởi tạo DB/WAL, 76 ghi event, 97 nối evidence |
| Detector lazy | v3 dòng 333–343; wrapper dòng 11 import detect_compat ở cấp module, constructor nạp model |
| Config | [config_compat](../../src/utils/config_compat.py), dòng 155–162 và 192–197; khác config.py cũ chỉ chứa constants |
| Đường gọi đối chứng | [common.py](../../debug/alert_diagnostics/common.py), dòng 18–21 import v3, contact_logic, geometry và config_compat |

Không thay `contacthands_compat` bằng wrapper cũ: [contacthands.py](../../src/core/contacthands.py), dòng 15–20, không nhận second_stream_config/weights/device mà v3 truyền vào.

## Phase D/E/F: kế thừa thay vì ba pipeline độc lập

~~~mermaid
flowchart TD
  E["Phase E OfflinePipeline"] --> AD["prediction_adapter"]
  E --> ST["StabilityProvider / Simulated / Correspondence"]
  E --> D["Phase D PipelineD"]
  D --> V4["PipelineV4"]
  D --> TD["TrackerD"]
  D --> TEMP["TemporalD"]
  D --> ENTRY["ROIEntry v4"]
  D --> BG["BackgroundStability"]
  V4 --> GEOM["src.core.geometry"]
  F["Phase F OfflineF"] --> E
  F --> PF["PipelineF kế thừa PipelineD"]
  PF --> D
  PF --> RT["RecoveryTracker kế thừa TrackerD"]
  PF --> DEFER["DeferredEntry / DeferredTemporal"]
  DEFER --> ENTRY
  DEFER --> TEMP
~~~

Bằng chứng:

- [pipeline_v4.py](../../debug/alert_diagnostics/v4/pipeline_v4.py), dòng 7–11: Tracker/ROIEntry/TemporalContact/geometry.
- [pipeline_d.py](../../debug/alert_diagnostics/v4/phase_d/pipeline_d.py), dòng 5–12: kế thừa PipelineV4, thay tracker/temporal/stability; disconnect trước dedup.
- [offline_pipeline.py](../../debug/alert_diagnostics/v4/phase_e/offline_pipeline.py), dòng 4–7: adapter và PipelineD; gọi cả API nội bộ `_gate` / `_clear_state` để xử lý freshness/lỗi. Đây là coupling cần regression trước mọi đổi tên.
- [pipeline_f.py](../../debug/alert_diagnostics/v4/phase_f/pipeline_f.py), dòng 3–7, lớp PipelineF/OfflineF: kết hợp lại D/E, giữ ROIEntry và TemporalD bằng wrapper trì hoãn.
- [recovery_tracker.py](../../debug/alert_diagnostics/v4/phase_f/recovery_tracker.py), dòng 3–15: TrackerD, geometry_recovery mặc định False, recovery window bị giới hạn.
- [stability.py](../../debug/alert_diagnostics/v4/phase_e/stability.py), dòng 6–17: mặc định UNKNOWN/stable=False. Chưa có bộ trích chuyển động ảnh thực đã được xác minh; không đổi UNKNOWN thành STABLE.

Geometry F opt-in có phản ví dụ nhầm tay còn FAIL trong [RESULTS](../../debug/alert_diagnostics/v4/phase_f/RESULTS.vi.md). Không tách module bằng copy-paste hoặc sửa gate cũ để biến báo cáo thành PASS.

## Import động, sys.path và registry

| Cơ chế | Bằng chứng | Rủi ro refactor |
|---|---|---|
| Thêm root/src vào sys.path | wrapper compat dòng 7–11; wrapper cũ dòng 5–7; [alignment test](../../tests/test_two_stream_alignment.py), dòng 17–18 | Cùng file có thể được nạp qua `src.*` hoặc tên top-level; đổi package dễ nạp trùng/che khuất thư viện |
| Package import tạo đăng ký | [two_stream/__init__](../../src/contact_hands_two_stream/__init__.py), dòng 1–6; [modeling/__init__](../../src/contact_hands_two_stream/modeling/__init__.py), dòng 1–2 | Star import hoặc import “không dùng biến” vẫn nạp registry |
| META_ARCH_REGISTRY | [first_stream_rcnn](../../src/contact_hands_two_stream/modeling/meta_arch/first_stream_rcnn.py), dòng 19; [second](../../src/contact_hands_two_stream/modeling/meta_arch/second_stream_rcnn.py), dòng 20 | YAML chọn FirstStreamRCNN/SecondStreamRCNN bằng tên |
| ROI_HEADS_REGISTRY | [first head](../../src/contact_hands_two_stream/modeling/roi_heads/first_stream_roi_head.py), dòng 26; [second head](../../src/contact_hands_two_stream/modeling/roi_heads/second_stream_roi_head.py), dòng 24 | Không bỏ import trước khi kiểm tra build_model |
| ROI_CONTACT_HEAD_REGISTRY | [contact_head](../../src/contact_hands_two_stream/modeling/roi_heads/contact_head.py), dòng 11, 84, 234 | ContactHead được lookup bằng chuỗi tên |
| DatasetCatalog/MetadataCatalog | [datasets/__init__](../../src/datasets/__init__.py); [load_data](../../src/datasets/load_data.py), dòng 84–93 | Đăng ký ContactHands_train/test/sub khi import; dirname tương đối ./ContactHands/ không phải root dataset thật đã được xác minh |
| importlib theo biến | alignment test dòng 34, 124, 144 dùng `contact_hands_two_stream.engine.second_stream_alignment`; [D runner](../../debug/alert_diagnostics/v4/phase_d/run_tests.py), dòng 51 | Tìm grep chỉ theo import statement có thể bỏ sót caller |
| __import__ | [inference/esp32.py](../../inference/esp32.py), dòng 29 nạp cv2 trong vòng lặp | Không kết luận dependency vắng chỉ vì không có import cv2 đầu file |
| Registry ORM | [migrations/env.py](../../web/backend/migrations/env.py), dòng 8; [0001](../../web/backend/migrations/versions/0001_initial_schema.py), dòng 5, 16 | Import models đăng ký metadata; không xóa “unused import” này |
| Entry web backend | [run_backend](../../web/scripts/run_backend.ps1) đặt cwd web/backend, dùng tên `app.*` | Chạy từ root bằng cùng module name có thể không tìm đúng package |

YAML `_BASE_`, tên kiến trúc/head và trọng số stream hai đều là phụ thuộc runtime cần giữ: [ContactHands.yaml](../../src/configs/ContactHands.yaml), [second_stream.yaml](../../src/configs/second_stream.yaml). Đường URI/cache không phải file dư.

## Side effect trước cả khi chạy main

- [tests/test_contacthands.py](../../tests/test_contacthands.py), dòng 12/21, tạo detector và inference ngay khi import: không chạy toàn bộ pytest/discovery.
- [web/backend/app/main.py](../../web/backend/app/main.py), dòng 28–29 tạo thư mục upload khi import.
- [video_demo.py](../../src/app/video_demo.py), dòng 13–15 và [yolo_pipeline.py](../../src/yolo_pipeline.py), dòng 10–12 gọi configure_runtime_paths khi import.
- [runtime_paths.py](../../tools/runtime_paths.py), dòng 44–61 tạo thư mục, ghi settings/cache và đặt biến môi trường.
- Runner D/E/F có thể ghi artifacts vào phase được bảo vệ dù test chỉ dùng prediction kiểm soát.

[tests/test_contact_logic.py](../../tests/test_contact_logic.py), dòng 6, kiểm tra `server.contact` của nhánh YOLO; không thay thế coverage cho `src/core/contact_logic.py` ContactHands.

Không xóa registry, đường import động, fixtures, checkpoint, schema cũ hay báo cáo FAIL. Xem [ứng viên rà soát](CLEANUP_CANDIDATES.vi.md) và [kế hoạch regression](SAFE_REFACTOR_PLAN.vi.md).
