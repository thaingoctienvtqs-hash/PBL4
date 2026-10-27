# Chuẩn bị đánh giá appearance-assisted recovery — ArtGuard

Ngày khảo sát: 2026-10-18 (Asia/Bangkok). Trạng thái: **CHƯA ĐỦ DỮ LIỆU ĐÁNH GIÁ**.

## Phạm vi đã thực hiện

Đọc ảnh, XML, JSON/JSONL và source hiện có; kiểm tra file tham chiếu; chuẩn bị tài liệu, JSON Schema và CSV chỉ có header. Không tạo crop, embedding, prediction, nhãn danh tính hoặc kết quả mô hình. Không chạy camera, GPU, train, database hay các runner B–F. Không sửa ngưỡng ContactHands.

Do chưa có dữ liệu danh tính tay theo thời gian có thể xác minh, lần này **chỉ cung cấp hướng dẫn thu thập và schema**. Không có extractor/evaluator hay mô hình Re-ID mới. JSON và CSV ở đây là hợp đồng dữ liệu, chưa được nối vào worker.

## Các tài liệu

- [DATA_AUDIT.vi.md](DATA_AUDIT.vi.md): kiểm kê thực tế và bằng chứng.
- [COLLECTION_PROTOCOL.vi.md](COLLECTION_PROTOCOL.vi.md): thu thập, gán nhãn, chia validation/test.
- [EVALUATION_DESIGN.vi.md](EVALUATION_DESIGN.vi.md): baseline appearance và thiết kế so sánh.
- [annotation_bundle.schema.json](annotation_bundle.schema.json): schema bundle dự kiến.
- Các `*.template.csv`: biểu mẫu **trống**, không phải dữ liệu đã gán nhãn.
- [data_inventory.json](data_inventory.json): kiểm kê các file đang có, không phải benchmark.
- [protected_before.json](protected_before.json), [verification.json](verification.json): hash trước/sau và kiểm tra tĩnh.

## Kết luận

ContactHands có bbox/polygon/contact label, chưa thấy nhãn danh tính hoặc frame timestamp trong toàn bộ XML. Các ảnh rời và ảnh cảnh báo của PBL4 chưa tạo thành tập đánh giá recovery. Các fixture B–F là dữ liệu logic kiểm soát; không dùng làm kết quả nhận diện ảnh thực.

Geometry recovery của F vẫn **không được bật làm mặc định**. Hướng appearance chỉ là thiết kế cần kiểm chứng. Khi thiếu bằng chứng danh tính, kết quả phải là **UNCERTAIN**; không chuyển ROI entry/history.

Accuracy >80%, Precision/Recall/F1 ≥80%: **CHƯA ĐÁNH GIÁ**. Không suy ra chất lượng AI từ kiểm tra tĩnh, unit test hoặc số lượng ảnh.

## Bước cần phê duyệt tiếp

Duyệt schema và kế hoạch gán nhãn trước. Sau đó có thể cung cấp một phiên video/raw frame có timestamp, hoặc phê duyệt riêng việc thu thập bằng luồng camera hiện có. Lần này chưa thực hiện bước đó.
