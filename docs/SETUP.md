# Hướng dẫn chạy PBL4 trên Windows và WSL

## 1. Môi trường

Inference ContactHands phụ thuộc vào Detectron2 cũ. Runtime đã được kiểm tra ngày 2026-10-12 trên WSL Ubuntu-22.04, conda env contacthands: Python 3.7.16, PyTorch 1.13.1+cu117, torchvision 0.14.1+cu117, Detectron2 0.1.1, OpenCV 5.0.0, CUDA 11.7 và GPU NVIDIA GeForce RTX 4060 Laptop. Một lần inference ảnh thật hoàn tất với exit code 0 khi dùng các đường dẫn thư viện CUDA bên dưới; ROI mặc định tắt nên worker trả NEEDS_CONFIGURATION, đây không phải kết quả đánh giá temporal hay độ chính xác. Dùng các lệnh sau để kiểm tra lại runtime hiện tại:

```bash
conda activate contacthands
python --version
python -c "import torch; print('torch', torch.__version__, 'CUDA build', torch.version.cuda, 'available', torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU mode')"
python -c "import detectron2; import detectron2._C; print('Detectron2:', detectron2.__file__); print('extension:', detectron2._C.__file__)"
```

Không chạy inference từ Windows Python nếu Detectron2 và extension biên dịch detectron2._C chưa tương thích. Các unit test PBL4 không cần model runtime và có thể chạy riêng trên Windows.

Dashboard cần FastAPI và Uvicorn. Nếu chúng chưa có trong môi trường, cài đúng hai dependency của web app bằng `python -m pip install -r requirements-app.txt`; file này không cài hoặc nâng cấp PyTorch/Detectron2.

## 2. Kiểm tra model và file cấu hình

Từ WSL:

```bash
cd /mnt/c/Users/LEGION/Pbl4
test -f models/combined_data_model.pth && ls -lh models/combined_data_model.pth
test -f src/configs/ContactHands.yaml
test -f src/configs/second_stream.yaml
```

`combined_data_model.pth` là checkpoint ContactHands. Luồng thứ hai dùng URI COCO chuẩn được khai báo trong `src/configs/second_stream.yaml`; Detectron2 cần tìm checkpoint trong cache của nó hoặc tải checkpoint trong môi trường có mạng. Có thể đặt `CONTACTHANDS_SECOND_STREAM_WEIGHTS` để trỏ tới file đã có. Không đặt đường dẫn cá nhân cố định trong source.

## 3. Chạy kiểm thử offline bằng một ảnh

Chạy trong WSL, không cần ESP32-CAM:

```bash
cd /mnt/c/Users/LEGION/Pbl4
conda activate contacthands
export CUDA_HOME=/usr/local/cuda
export PATH="$CUDA_HOME/bin:$PATH"
export LD_LIBRARY_PATH="/usr/lib/wsl/lib:$CUDA_HOME/lib64:${LD_LIBRARY_PATH:-}"
export TORCH_CUDA_ARCH_LIST="8.6"
python -m src.realtime_worker --mode image --image /mnt/c/Users/LEGION/PaintingProtection/webcam_frame.jpg --device cuda
```

Thay `--image` bằng một file ảnh thật khác nếu file trên không tồn tại. Đầu ra đã chú thích ở `src/data/latest.jpg`; trạng thái/sự kiện ở `src/data/events.sqlite3`. Cấu hình ROI mặc định đang tắt nên chưa phát cảnh báo cho tới khi ROI được bật.

Chạy thư mục ảnh offline:

```bash
python -m src.realtime_worker --mode image-dir --image-dir /path/to/real/images --device cuda
```

## 4. Chạy unit test không cần model

Trong WSL hoặc Windows:

```bash
python -m unittest discover -s tests -v
```

Các test dùng ảnh tạm và SQLite tạm; không dùng webcam, checkpoint hay dataset thật. `tests/test_contacthands.py` là smoke test riêng, chỉ chạy khi được gọi trực tiếp với `--image`.

## 5. Chụp ảnh ESP32-CAM trên Windows

Mở PowerShell tại `C:\Users\LEGION\Pbl4`, đặt URL `/capture` vào biến môi trường chỉ trong terminal hiện tại rồi chạy capture:

```powershell
$env:PBL4_CAMERA_URL = 'http://<ESP32-CAM-IP>/capture'
py -3 .\esp32cam_capture.py --output .\data\camera_frame.jpg
```

Script chỉ dùng Python standard library, có timeout, kiểm tra JPEG và ghi file tạm cùng thư mục trước khi `os.replace`. Lỗi mạng được báo là `CAMERA_DISCONNECTED`; tiến trình tiếp tục thử lại. Dừng bằng `Ctrl+C`.

Không lưu IP camera, mật khẩu Wi-Fi hoặc token vào Git. Có thể truyền URL qua `--camera-url` thay cho biến môi trường.

## 6. Chạy inference thời gian thực qua file dùng chung

Để tách capture Windows khỏi GPU inference WSL, chạy hai terminal:

**Terminal Windows:** chạy lệnh capture ở mục 5. File mặc định nằm trong `Pbl4\data\camera_frame.jpg`.

**Terminal WSL:**

```bash
cd /mnt/c/Users/LEGION/Pbl4
conda activate contacthands
export CUDA_HOME=/usr/local/cuda
export LD_LIBRARY_PATH="/usr/lib/wsl/lib:$CUDA_HOME/lib64:${LD_LIBRARY_PATH:-}"
export TORCH_CUDA_ARCH_LIST="8.6"
python -m src.realtime_worker --mode file-watch --frame-file /mnt/c/Users/LEGION/Pbl4/data/camera_frame.jpg
```

Worker hiển thị `WAITING_FOR_FRAME` hoặc `MONITORING` khi chờ ảnh; `CAMERA_DISCONNECTED` hoặc `ERROR` khi nguồn/model lỗi; `NEEDS_CONFIGURATION` khi ROI chưa bật; và `NO_HAND`, `OUTSIDE_ROI`, `NO_CONTACT`, `CANDIDATE`, `ALERT` hoặc `COOLDOWN` theo detection và lịch sử từng track. Một lần tiếp xúc chỉ tạo event khi track chuyển sang `ALERT`; evidence chứa ROI, bbox, track ID, score, overlap và lý do. Dừng bằng `Ctrl+C`.

Có thể để WSL gọi thẳng camera nếu mạng WSL truy cập được ESP32-CAM:

```bash
python -m src.realtime_worker --mode camera --camera-url "http://<ESP32-CAM-IP>/capture"
```

Kết nối này chưa được xác minh trong phiên làm việc.

## 7. Dashboard và cấu hình ROI

Trong terminal WSL thứ ba:

```bash
cd /mnt/c/Users/LEGION/Pbl4
conda activate contacthands
python -m uvicorn src.app.api:app --host 127.0.0.1 --port 8000
```

Mở `http://localhost:8000/`. Dashboard hiển thị ảnh đã xử lý, trạng thái worker, trạng thái cảm biến, cảnh báo đã lưu và lịch sử cũ. Cấu hình ROI theo tọa độ chuẩn hóa `[x1,y1,x2,y2]` từ 0 đến 1 rồi bật ROI. Worker đọc lại cấu hình theo từng frame.

Ngưỡng Object-Contact 0.15 và các ngưỡng temporal là giá trị thử ban đầu, chưa được tối ưu. Worker ghép bàn tay bằng IoU/khoảng cách tâm chuẩn hóa; xác nhận 3/5 frame hoặc 2 frame liên tiếp ở score cao sau khi track đi vào ROI. Đứng yên sau 2 giây chỉ là thông tin, không phải điều kiện cảnh báo. Cần hiệu chuẩn ROI và đánh giá video chạm/không chạm có nhãn. RGB không luôn phân biệt được tay thật với hình bàn tay có sẵn trong tranh.

## 8. Khởi chạy bằng batch trên Windows

```cmd
set PBL4_CAMERA_URL=http://<ESP32-CAM-IP>/capture
start_pbl4.bat
```

Batch khởi chạy API/dashboard và worker trong WSL cùng script chụp ảnh Windows. Nó dùng đường dẫn `C:\Users\LEGION\Pbl4` và distro `Ubuntu-22.04` trong cấu hình hiện tại. Nếu cài đặt khác, cập nhật đường dẫn/distro trong batch trước khi chạy. Tắt từng terminal để dừng dịch vụ.

## 9. Dữ liệu, lịch sử và cảm biến

- SQLite runtime: `src/data/events.sqlite3`; status và events còn sau khi khởi động lại.
- Ảnh xử lý gần nhất: `src/data/latest.jpg`.
- Ảnh evidence chỉ lưu khi tạo event mới sau cooldown: `src/data/alerts/`.
- `src/data/history.json` là lịch sử JSON cũ được đọc để hiển thị; code mới không ghi đè hoặc xóa file này.
- Chưa có firmware/protocol cho PIR, khoảng cách hoặc GPIO. Adapter `UnconfiguredSensor` trả `UNKNOWN`; adapter mock không giả vờ có cảm biến thật.

## 10. Sự cố thường gặp

- `ContactHands initialization failed`: kiểm tra Python/Detectron2 trong conda `contacthands`, hai YAML và `models/combined_data_model.pth`.
- Không tải được luồng thứ hai: kiểm tra checkpoint COCO trong iopath cache hoặc đặt `CONTACTHANDS_SECOND_STREAM_WEIGHTS` tới file có thật.
- `CAMERA_DISCONNECTED`: kiểm tra URL `/capture`, Wi-Fi, cùng mạng và thử mở URL trên Windows; chạy script capture bằng `--once` để kiểm tra một ảnh.
- `WAITING_FOR_FRAME`: đảm bảo Windows và WSL trỏ cùng file `data/camera_frame.jpg`.
- `NEEDS_CONFIGURATION`: đặt ROI trên dashboard; ROI tắt có chủ ý khi khởi tạo.
- Dataset không hợp lệ: chạy validator, kiểm tra Pascal VOC XML và các cột `xmin/ymin/xmax/ymax`, polygon `x1..x4/y1..y4`, `contact_state`.
- Test offline qua nhưng inference không chạy: unit test không cần model; inference cần môi trường WSL/Detectron2 và checkpoint thật.
