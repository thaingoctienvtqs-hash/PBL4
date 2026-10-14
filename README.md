# PBL4 — Hệ thống giám sát và bảo vệ tranh

PBL4 kết hợp ContactHands, camera ESP32-CAM, ROI tranh, lưu trạng thái/sự kiện và dashboard. ContactHands phân loại điểm tiếp xúc của bàn tay; một dự đoán AI trong ROI được ghi là **nghi vấn cần người xác minh**, không phải bằng chứng chắc chắn tay đã chạm tranh.

## Trạng thái repository

- Mã ContactHands hai luồng và checkpoint chính `models/combined_data_model.pth` có trong bản làm việc hiện tại. Checkpoint COCO cho luồng thứ hai được nạp qua URI chuẩn của Detectron2 và cần có trong iopath cache hoặc được tải trong môi trường có mạng.
- Thư mục `dataset/` hiện không có ảnh/annotation ContactHands. Chưa xác minh được dataset ArtInsight trong máy; định dạng ArtInsight không tự động tương thích với nhãn ContactHands.
- ROI tắt ban đầu. Cần cấu hình ROI thực tế trong dashboard trước khi worker được phép tạo cảnh báo.
- Chưa có adapter cảm biến thật. Trạng thái cảm biến là `UNKNOWN`; chế độ mock chỉ dùng cho unit test.

## Thành phần

- `src/realtime_worker.py`: inference offline, đọc file ảnh atomically cập nhật hoặc lấy ảnh trực tiếp từ ESP32-CAM.
- `esp32cam_capture.py`: tiến trình Windows lấy JPEG từ endpoint `/capture` và thay file ảnh nguyên tử.
- `src/app/api.py` + `index.html`: dashboard, cấu hình ROI/ngưỡng, trạng thái, ảnh mới nhất và lịch sử.
- `src/services/event_store.py`: SQLite lưu trạng thái hiện thời và lịch sử; cooldown ngăn ghi lặp.
- `src/datasets/tools.py`: kiểm tra dữ liệu Pascal VOC, đếm nhãn và tạo ảnh xem annotation.
- `tests/test_core.py`: unit test không cần camera, CUDA, Detectron2 hoặc dataset.

## Cài đặt và chạy

Xem [docs/SETUP.md](docs/SETUP.md) để biết lệnh cho Windows/WSL, chạy inference offline, camera, dashboard và xử lý lỗi.

Kiểm tra dataset:

```bash
python -m src.datasets.tools validate --root /path/to/ContactHands
python -m src.datasets.tools stats --root /path/to/ContactHands --json
python -m src.datasets.tools preview --root /path/to/ContactHands --split test --limit 12 --output-dir /tmp/contacthands-preview
```

Chạy unit test:

```bash
python -m unittest discover -s tests -v
```

Integration smoke test cần checkpoint và ảnh thật; xem `tests/test_contacthands.py`. Kết quả smoke test không phải thước đo độ chính xác.

## Dữ liệu và quyền riêng tư

Đặt dataset tại `dataset/contacthands/` hoặc trỏ `CONTACTHANDS_DATA_ROOT` tới vị trí thực tế. Ảnh camera, frame mới nhất, SQLite, evidence và checkpoint lớn nằm ngoài Git. Đặt URL camera bằng biến môi trường `PBL4_CAMERA_URL`; không commit địa chỉ IP riêng hoặc thông tin mạng.

ContactHands là mã/dataset cho phát hiện bàn tay và nhãn tiếp xúc. ArtInsight được tham khảo cho tình trạng tranh; không đưa dữ liệu ArtInsight trực tiếp vào huấn luyện ContactHands khi chưa chuyển đổi định dạng và xác minh nhãn.

## Nguồn tham khảo

- [ContactHands source repository](https://github.com/cvlab-stonybrook/ContactHands)
- [PBL4 repository](https://github.com/thaingoctienvtqs-hash/PBL4)
- [ROI calibration and labeled-video evaluation procedure](docs/ROI_EVALUATION.md)
- Narasimhas, Nguyen, Hoai. *Detecting Hands and Recognizing Physical Contact in the Wild*, NeurIPS 2020.
