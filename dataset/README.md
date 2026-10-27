# Dataset PBL4: trạng thái và chuẩn bị

## Dataset thực sự có trên máy

Trong repo PBL4 tại thời điểm khảo sát, thư mục `dataset/` chỉ có `.gitkeep` và tài liệu; chưa có ảnh, annotation XML hoặc split list. Vì vậy không có thống kê số ảnh/nhãn thực tế để báo cáo. Chạy `python -m src.datasets.tools validate --root <dataset-root>` sau khi chuẩn bị dataset; validator sẽ báo rõ file thiếu thay vì sinh dữ liệu mẫu.

## ContactHands gốc

Dataset ContactHands dành cho phát hiện bàn tay và bốn nhãn tiếp xúc. Thư mục mà loader hỗ trợ có cấu trúc Pascal VOC:

- Mã nguồn: [cvlab-stonybrook/ContactHands](https://github.com/cvlab-stonybrook/ContactHands)
- Trang dataset được dự án tham khảo: [ContactHands dataset](https://vision.cs.stonybrook.edu/~supreeth/ContactHands_data_website/)

```text
contacthands/
├── JPEGImages/<image-id>.jpg
├── Annotations/<image-id>.xml
└── ImageSets/Main/{train,test,sub}.txt
```

Đặt dữ liệu tại `dataset/contacthands/` hoặc chỉ định `CONTACTHANDS_DATA_ROOT` trong terminal. Dữ liệu lớn không được commit.

Mỗi XML cần kích thước ảnh, từng object lớp `hand`, bounding box VOC `xmin/ymin/xmax/ymax`, bốn điểm polygon trong `x1..x4/y1..y4` và `contact_state` gồm đúng bốn giá trị. Thứ tự nhãn theo ContactHands:

1. `No-Contact`
2. `Self-Contact`
3. `Other-Person-Contact`
4. `Object-Contact`

`0` là âm tính, `1` là dương tính, `2` là chưa chắc chắn. Loader gốc loại các hàng có nhãn chưa chắc chắn khỏi loss ContactHands; đừng đổi `2` thành `0` nếu chưa có người gán nhãn xác nhận.

## Dataset tự thu thập

Chưa có ảnh tự thu thập được gán nhãn để đưa vào huấn luyện. Khi tạo bộ dữ liệu, ghi rõ phiên camera, ảnh, ROI tranh, bounding box tay và nhãn tiếp xúc; thêm ví dụ âm tính khó như tay gần tranh nhưng không chạm. Chia train/validation/test theo phiên quay hoặc người, tránh để các frame gần như trùng nhau xuất hiện ở nhiều split. Giữ bản gốc chỉ đọc và lưu annotation ở bản sao có version.

Các nhãn `touching_painting` và `not_touching_painting` của nhóm là nhãn bài toán riêng, không tương đương trực tiếp với `Object-Contact`. Muốn dùng để train ContactHands phải ánh xạ rõ định nghĩa và chuyển annotation sang định dạng tương thích, rồi kiểm tra độc lập.

## ArtInsight

ArtInsight được tham khảo cho tình trạng xuống cấp/bảo tồn tranh. Đây không phải mặc định là dữ liệu phát hiện bàn tay/tiếp xúc của ContactHands. Chưa tìm thấy bản dataset ArtInsight trong thư mục dự án; không có lệnh tải hoặc huấn luyện nào giả định dataset này tồn tại. Chỉ kết hợp sau khi kiểm tra license, định dạng và nhiệm vụ nhãn thực tế.

- [ArtInsight record on Zenodo](https://zenodo.org/records/15640972)
- [ArtInsight on Hugging Face](https://huggingface.co/datasets/biglam/artinsight-painting-deterioration)

## Kiểm tra và thống kê

```bash
python -m src.datasets.tools validate --root /path/to/contacthands
python -m src.datasets.tools stats --root /path/to/contacthands --json
python -m src.datasets.tools preview --root /path/to/contacthands --split test --limit 12 --output-dir /tmp/contacthands-preview
```

Validator đọc danh sách ảnh, XML, class, tọa độ box/polygon, nhãn bốn trạng thái và kích thước ảnh. Preview vẽ annotation có thật; script không tạo ảnh/annotation giả và không sửa dataset gốc.

