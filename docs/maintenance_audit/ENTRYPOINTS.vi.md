# ArtGuard — Entrypoint và lệnh chạy

Đối chiếu source ngày 18/10/2026. **Các lệnh runtime bên dưới chỉ để tra cứu, không được chạy trong Nhóm 1.** Chúng có thể mở camera/GPU, tạo file hoặc kết nối DB. CLI được đọc tĩnh, không gọi cả `--help` của module có side effect khi import.

## Phân loại

- **ACTIVE**: entrypoint của nhánh hiện đang được dùng/phát triển theo source và báo cáo nhóm; không bảo đảm dịch vụ đang chạy hoặc AI đã tích hợp website.
- **LEGACY**: luồng cũ, bản phục hồi hoặc bản chuyển tiếp; giữ làm đối chứng.
- **EXPERIMENTAL**: thử nghiệm riêng/offline hoặc nhánh thay thế chưa phê duyệt triển khai.

| Phân loại | Entrypoint có thật | Môi trường / lưu ý |
|---|---|---|
| ACTIVE — AI baseline | [worker v3](../../src/realtime_worker_integrated_v3.py), `main` dòng 507, parser 487–504 | WSL Conda contacthands; file-watch đã được nhóm báo cáo chạy |
| ACTIVE — website demo | [run_backend.ps1](../../web/scripts/run_backend.ps1), dòng 7 | Windows backend virtualenv; `app.main:app`; có ghi upload/DB khi sử dụng |
| ACTIVE — website demo | [run_frontend.ps1](../../web/scripts/run_frontend.ps1), dòng 6 | Windows Node/Vite; không phải index.html gốc |
| LEGACY | [start_pbl4.bat](../../start_pbl4.bat), dòng 10, 15, 18, 21 | Mở nhiều tiến trình; trỏ API/realtime/dashboard cũ và producer ngoài repo |
| LEGACY | [src.app.realtime](../../src/app/realtime.py), [src.app.api](../../src/app/api.py), [src.app.main](../../src/app/main.py) | ContactHands wrapper cũ, history JSON/status text; main mở webcam |
| LEGACY / chuyển tiếp | [integrated](../../src/realtime_worker_integrated.py), [v2](../../src/realtime_worker_integrated_v2.py), [recovered](../../src/realtime_worker_recovered.py), [verified](../../src/realtime_worker_verified.py) | Có import/constructor không khớp; không chọn thay v3 |
| EXPERIMENTAL | [Phase D runner](../../debug/alert_diagnostics/v4/phase_d/run_tests.py), [E replay](../../debug/alert_diagnostics/v4/phase_e/replay.py), [F replay](../../debug/alert_diagnostics/v4/phase_f/replay_f.py) | Logic/JSONL; runner vẫn tạo artifacts, không chạy trong lượt tài liệu |
| EXPERIMENTAL — YOLO | [src.app.video_demo](../../src/app/video_demo.py), [src.app.yolo_main](../../src/app/yolo_main.py), [src.yolo_pipeline](../../src/yolo_pipeline.py) | Python hiện đại; Ultralytics; weights và outputs riêng |
| EXPERIMENTAL — camera tools | [inference.webcam](../../inference/webcam.py), [inference.esp32](../../inference/esp32.py), [dataset_collector](../../inference/dataset_collector.py) | Mở camera/ghi ảnh; không chạy đồng thời với producer chính |

`src/realtime_worker.py` tồn tại nhưng **0 byte**, không có CLI hoạt động. `src/calibrate_roi.py` không tồn tại trong source hiện tại. Không khuyến nghị lệnh cho hai đường dẫn này chỉ vì tài liệu cũ nhắc tới.

## ContactHands v3 — Ubuntu WSL

Thư mục làm việc: `/mnt/c/Users/LEGION/Pbl4`. Interpreter đã kiểm tra tồn tại và trả Python 3.7.16:
`/home/legion/miniconda3/envs/contacthands/bin/python` trong distro **Ubuntu**.

Mẫu lệnh dưới đây cố ý có placeholder `CONFIG_JSON_DA_HIEU_CHUAN`: phải cung cấp file thật đã kiểm tra ROI, model và output riêng trước khi chạy; đây chưa phải lệnh sẵn sàng chạy trên cấu hình hiện tại.

~~~bash
cd /mnt/c/Users/LEGION/Pbl4
/home/legion/miniconda3/envs/contacthands/bin/python -B -m src.realtime_worker_integrated_v3 --mode file-watch --frame-file /mnt/c/Users/LEGION/Pbl4/data/camera_frame.jpg --config-json CONFIG_JSON_DA_HIEU_CHUAN
~~~

Parser xác nhận các mode `camera/file-watch/image/image-dir`; các cờ:
`--config-json`, `--config`, `--weights`, `--second-stream-config`, `--second-stream-weights`, `--device auto|cpu|cuda`, `--camera-url`, `--frame-file`, `--image`, `--image-dir`, `--database`, `--poll-interval`, `--once`.

`--once` chỉ giới hạn xử lý frame; **vẫn khởi tạo EventStore/model và có thể ghi**. Mode image đơn lẻ không đủ chứng minh temporal ALERT. Không dùng camera mode khi producer khác đang lấy ảnh. Cấu hình JSON mặc định `configs/pbl4.json` và `configs/pbl4_test.json` hiện không có; loader có fallback, ROI mặc định tắt. Không coi fallback là cấu hình hiệu chuẩn.

## Website — PowerShell Windows

Từ root PBL4, sau khi được phép chạy dịch vụ và xác minh cấu hình riêng:

~~~powershell
Set-Location 'C:/Users/LEGION/Pbl4'
& './web/scripts/run_backend.ps1'
~~~

Terminal khác:

~~~powershell
Set-Location 'C:/Users/LEGION/Pbl4'
& './web/scripts/run_frontend.ps1'
~~~

Backend script dùng `web/backend/.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload` từ cwd backend. Frontend dùng `npm.cmd run dev` từ cwd frontend; Vite mặc định 5173, proxy API về 8000. Backend demo và API cũ tranh cùng cổng 8000; không chạy chung.

Các script `setup_backend.ps1` / `setup_frontend.ps1` là **cài đặt**, không thuộc Nhóm 1. `run_tests.ps1` có pytest và build, không phải kiểm tra chỉ đọc. Không chạy seed/migration để “thử kết nối”.

## Replay offline — ví dụ hiện có, chưa chạy lại

Từ WSL root PBL4, E replay có đủ module và fixture trên đĩa:

~~~bash
/home/legion/miniconda3/envs/contacthands/bin/python -B -m debug.alert_diagnostics.v4.phase_e.replay --input debug/alert_diagnostics/v4/phase_e/fixtures/slow_entry.jsonl --config debug/alert_diagnostics/v4/phase_e/fixtures/slow_entry.settings.json --simulate-stability
~~~

F mặc định bảo thủ, không thêm cờ geometry recovery:

~~~bash
/home/legion/miniconda3/envs/contacthands/bin/python -B -m debug.alert_diagnostics.v4.phase_f.replay_f --input debug/alert_diagnostics/v4/phase_f/fixtures/explicit_missing_frame.jsonl --config debug/alert_diagnostics/v4/phase_f/fixtures/timeout2.settings.json --simulate-stability
~~~

Hai lệnh **tạo thư mục runs mới trong E/F**; cần phê duyệt ghi artifacts vào các phase đang bảo vệ trước khi dùng. `--simulate-stability` chỉ dành fixture kiểm soát. F có `--geometry-recovery` nhưng chưa phê duyệt dùng mặc định vì còn phản ví dụ nhầm danh tính. Exit 0 của replay không chứng minh độ chính xác AI hay camera ổn định. Xem [kết quả F đã lưu](../../debug/alert_diagnostics/v4/phase_f/RESULTS.vi.md).

## Nhánh YOLO — hợp đồng CLI, chưa đủ điều kiện chạy

`python -B -m src.app.video_demo` có một trong `--input`, `--webcam`, `--esp32-url`; kèm `--config`, `--weights`, `--output`, `--events`, `--evidence-dir`, `--use-hand-landmarker` (source dòng 32–46). Không đưa lệnh camera chạy sẵn.

`configs/system.toml` tồn tại; weights YOLO mặc định ở root chưa có. Wrapper `tools/run_pbl4.py --venv ... -- ...` dùng đường dẫn interpreter Windows; mặc định `.venv-py314/Scripts/python.exe` hiện không tồn tại. Không lấy Conda 3.7 hoặc backend virtualenv làm môi trường YOLO khi chưa kiểm tra dependency.

## Cảnh báo launcher cũ

`start_pbl4.bat` dùng distro `Ubuntu-22.04`, `src.app.api:app`, `src.app.realtime`, producer `C:/Users/LEGION/PaintingProtection/webcam_contacthands.py`, rồi HTTP server 8080 cho `index.html` gốc. Đây **không phải launcher tích hợp website ArtGuard hiện tại**. Không sửa hay chạy launcher trong Nhóm 1; không sửa script ngoài PBL4.

Xem [môi trường](ENVIRONMENTS.vi.md) và [kế hoạch phê duyệt từng nhóm](SAFE_REFACTOR_PLAN.vi.md).
