# PBL4 - Setup môi trường

## 1. Clone repository

```bash
git clone https://github.com/thaingoctienvtqs-hash/PBL4.git
cd PBL4
```

## 2. Kiểm tra Python

Khuyến nghị Python 3.7 cho môi trường ContactHands/Detectron2 hiện tại.

```bash
python --version
```

## 3. Cấu trúc source

Source code ContactHands nằm trong thư mục `src/`.

```text
src/
├── configs/
├── contact_hands_two_stream/
├── detect.py
└── realtime_worker.py
```

## 4. Model

Các checkpoint lớn không được commit trực tiếp lên GitHub.
Model cần được đặt trong thư mục `models/`.

## 5. Dataset

Xem `dataset/README.md` để biết nguồn dataset và cách chuẩn bị dữ liệu.

## 6. Lưu ý

Không commit các file lớn như dataset, `.pth`, `.pkl`, `.pt`, `.onnx`.
