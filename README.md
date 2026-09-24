# PBL4 - Hệ thống giám sát và bảo vệ tranh

## Mục tiêu
Xây dựng hệ thống giám sát tranh bằng Computer Vision và AI nhằm phát hiện người tiếp xúc với khu vực tranh và đưa ra cảnh báo.

## Chức năng dự kiến
- Phát hiện người trong khu vực giám sát.
- Phát hiện bàn tay và trạng thái tiếp xúc.
- Xác định vùng tranh (ROI).
- Cảnh báo khi phát hiện tiếp xúc với tranh.
- Lưu lịch sử cảnh báo.
- Tích hợp cảm biến phần cứng trong các giai đoạn tiếp theo.

## Cấu trúc dự án

```text
Pbl4/
├── dataset/
├── src/
├── configs/
├── models/
├── tests/
├── docs/
├── README.md
└── .gitignore
```

## Công nghệ
- Python
- OpenCV
- PyTorch
- Detectron2
- ContactHands
- Computer Vision

## Dataset
Dataset lớn không được commit trực tiếp vào repository.
Thông tin và hướng dẫn tải dataset sẽ được đặt trong thư mục dataset/.

## Thành viên
- Team PBL4
