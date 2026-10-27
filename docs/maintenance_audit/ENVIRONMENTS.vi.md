# ArtGuard — Bản đồ môi trường

Ngày đối chiếu: 18/10/2026. Chỉ kiểm tra đường dẫn, phiên bản interpreter/Node và metadata package. Không cài đặt, import model, chạy CUDA hay truy vấn SQL Server; không đọc nội dung `.env`.

## Windows, WSL và phiên bản

| Thành phần | Bằng chứng hiện có | Giới hạn |
|---|---|---|
| Root Windows | `C:/Users/LEGION/Pbl4` | Không dùng repo ContactHands gốc làm đích sửa |
| Root WSL | `/mnt/c/Users/LEGION/Pbl4` | Cùng file NTFS; Git/line ending có thể được diễn giải khác |
| WSL Conda contacthands | Interpreter `/home/legion/miniconda3/envs/contacthands/bin/python -B` trả **3.7.16** | Xác minh trong distro **Ubuntu**; không suy ra distro Ubuntu-22.04 giống hệt |
| Windows backend virtualenv | `web/backend/.venv/Scripts/python.exe -B --version` trả **3.14.7** | Khác mốc 3.11 trong tài liệu; chưa kiểm tra import/backend/ODBC trên phiên bản này |
| Windows Python khai báo | [.python-version](../../.python-version) ghi **3.11.9**; [web README](../../web/README.md) yêu cầu 3.11+ | Là khai báo, không chứng minh interpreter đang dùng |
| Python launcher Windows | `py -0p` bị hệ thống chặn: “The file cannot be accessed by the system” | BLOCKED; không cài lại hoặc tự sửa launcher |
| Node.js | `node --version` trả **v24.22.0** | Không đồng nghĩa npm/build đã được chạy kiểm tra |
| Frontend | [package.json](../../web/frontend/package.json): React ^19.1.0, Vite ^6.3.5, TypeScript ~5.8.3 | Phiên bản khai báo; không phải kết quả npm audit/build |
| SQL Server | SQLAlchemy/pyodbc được cấu hình cho SQL Server khi không testing | Không kết nối, kiểm tra service hay truy vấn version trong Nhóm 1 |

Không đồng nhất “Windows Python”, Python hệ thống WSL và Conda contacthands. Không chạy pip để ép các môi trường thành một.

## ContactHands: gói và GPU

Kiểm tra bằng cách đọc metadata trong Conda, không import torch/Detectron2:

- PyTorch metadata: **1.13.1+cu117**.
- Pillow metadata: **9.5.0**.
- `detectron2.egg-link` trỏ tới `/home/legion/detectron2`; source `detectron2/__init__.py` khai báo **0.1.1**.
- Không thấy file khớp `_C*.so` ngay trong thư mục package editable vừa đọc. **Chưa xác minh import `detectron2._C`**, không kết luận cần cài lại: cần kiểm tra đường nạp/đường build trong một lượt được duyệt riêng.
- RTX 4060 Laptop, CUDA hoạt động và inference ContactHands thành công là **thông tin nhóm đã báo cáo trước**. Lượt này không chạy `torch.cuda.is_available()`, `nvidia-smi` hoặc inference để xác minh lại.

[Launcher cũ](../../start_pbl4.bat), dòng 10/15, export CUDA_HOME, LD_LIBRARY_PATH và TORCH_CUDA_ARCH_LIST. Các giá trị trong launcher là cấu hình lịch sử, không phải phép đo tương thích GPU hiện tại. Không sao chép chúng để ghi đè môi trường đang hoạt động.

[detect_compat](../../src/detect_compat.py), dòng 61–104, có chọn CPU nếu auto và CUDA không khả dụng; đây là hành vi source, chưa chạy thử. Weight stream hai có thể lấy cache hoặc URI Detectron2: gọi constructor có thể truy cập mạng/cache. Giữ cả checkpoint chính và cache hiện có.

## Các nhóm dependency riêng

| Nhánh | Nguồn khai báo / code | Điểm cần bảo vệ |
|---|---|---|
| ContactHands baseline | [contacthands_compat](../../src/core/contacthands_compat.py), [detect_compat](../../src/detect_compat.py), source two-stream | Python 3.7 + bộ PyTorch/Detectron2 cũ; không cài requirements website/YOLO vào Conda này |
| Website backend | [requirements](../../web/backend/requirements.txt): FastAPI 0.115.12, SQLAlchemy 2.0.40, pyodbc 5.2.0, Alembic 1.15.2 | Là phiên bản pin trong file, chưa xác minh toàn bộ package đã cài |
| Frontend | [package](../../web/frontend/package.json), package-lock hiện có thay đổi từ trước | Không npm install/upgrade, không ghi lại lockfile |
| YOLO / tay tùy chọn | [requirements-server](../../requirements-server.txt), [requirements-hands](../../requirements-hands.txt), [video_demo](../../src/app/video_demo.py) | `tomllib` cần Python 3.11+ theo stdlib; annotation hiện đại không phù hợp Conda 3.7 |
| Phase D/E/F | Logic Python, tái sử dụng geometry và baseline cho so sánh | CLI runner có thể tạo artifacts dù không dùng GPU |

`requirements-hands.txt` là thành phần localization tay tùy chọn; không phải hướng dẫn tái tạo môi trường ContactHands đã chạy thành công. Backend requirements pin Pillow khác Conda; không đồng bộ tự động.

## SQL Server và cấu hình riêng tư

[web/README.md](../../web/README.md) lưu báo cáo ngày 14/10/2026 về SQL Server 2022 **Developer** và ODBC Driver 17. Bối cảnh nhóm từng nêu **Express**. Edition/instance hiện chạy: **CHƯA XÁC MINH**; không dùng một trong hai làm kết luận hiện tại.

[app/db.py](../../web/backend/app/db.py), dòng 13–20, chọn SQLite memory khi testing, SQL Server cho runtime thông thường. Việc tests dùng SQLite không chứng minh SQL Server hoạt động. [models](../../web/backend/app/models.py) và [migrations](../../web/backend/migrations/env.py) mô tả bảng, không xác nhận schema DB thực tế đã áp dụng.

`web/.env` hiện không có ở đường dẫn kiểm tra; `web/.env.example` đã được sửa trước Nhóm 1 và được bảo vệ. Không đọc/copy nội dung hai file vào bộ tài liệu này, không kết xuất biến môi trường hoặc connection string. Thiết lập thực tế có thể đến từ process environment; chưa thu thập giá trị.

## Ưu tiên cấu hình worker v3

Theo [config_compat](../../src/utils/config_compat.py), dòng 155–162:

1. Tham số `--config-json` truyền tới load_settings.
2. Khi không truyền, dùng biến `PBL4_CONFIG`.
3. Sau đó mới dùng `configs/pbl4.json`; thiếu file thì fallback DEFAULTS, ROI tắt.
4. Override trong validate_settings: `PBL4_CAMERA_URL`, `CONTACTHANDS_MODEL_WEIGHTS`, `CONTACTHANDS_SECOND_STREAM_WEIGHTS`.
5. Đường dữ liệu qua resolve_path dùng `PBL4_CAPTURE_FRAME`, `PBL4_LATEST_FRAME`, `PBL4_EVENT_DB`, `PBL4_STATUS_FILE`, `PBL4_EVIDENCE_DIR`.
6. Worker còn xử lý CLI model/device/frame/database/poll trước khi chạy; xem dòng 333–343, 380–418.

Đây là thứ tự theo code, **không phải snapshot các biến môi trường của lần inference trước**. Không thể suy ngược config cũ từ DEFAULTS hiện tại. `configs/pbl4.json` và `configs/pbl4_test.json` đang thiếu; bản `pbl4_test.json.before_cooldown` không tự được load.

## Git, newline và LFS

Lấy **Git Windows** làm mốc trạng thái của lượt này. Cấu hình Git Windows có autocrlf/LFS khác WSL; WSL có thể báo nhiều file thay đổi do filter, dù bytes chưa đổi. Không normalize newline, chạy LFS checkout, sửa gitconfig hoặc dùng reset/restore để làm sạch.

Checkpoint chính SHA-256:
`c03f38a947d426b39b7538a5478f823799d98b34e0fb299ec35a6520342a342a`.

Object tương ứng trong `.git/lfs/objects` là bộ phận Git LFS cần giữ. Kiểm kê dung lượng không phải giấy phép xóa model, venv, node_modules hay Git objects. Xem [bản đồ phụ thuộc](DEPENDENCIES.vi.md) và [quy trình thay đổi an toàn](SAFE_REFACTOR_PLAN.vi.md).
