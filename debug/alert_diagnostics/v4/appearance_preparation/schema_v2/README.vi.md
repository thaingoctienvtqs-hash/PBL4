# ArtGuard annotation v2 — camera sát mép trên tranh

Trạng thái: chuẩn bị annotation và kiểm thử hợp đồng dữ liệu, **không phải phiên bản AI mới**.

Camera chính ESP32-CAM OV3660 gắn trực tiếp sát mép trên khung tranh: `TOP_EDGE_DIRECT`, nhìn xiên xuống dọc bề mặt: `OBLIQUE_DOWNWARD`. Chưa đo góc nghiêng/FOV/độ phủ/vùng mù thật. Không có file config ROI thật được tạo trong bộ này.

## File và phạm vi

- `annotation_bundle.v2.schema.json`: schema mới, giữ nguyên ../annotation_bundle.schema.json v1.
- `validate_v2.py`: CLI read-only; kiểm tra cấu trúc thuộc tập keyword của schema này và ngữ nghĩa/reference/geometry. **Không phải implementation đầy đủ hay chứng nhận tương thích Draft 7**.
- `synthetic_cases.py`, `fixtures/*SYNTHETIC_TEST.json`, `test_schema_v2.py`: dữ liệu và test hợp đồng tổng hợp. Không có ảnh/video thật hoặc giả được tạo.
- `run_schema_checks.py`: chạy test logic, parse AST/JSON; báo cáo mới có tên riêng dưới runs/, không ghi đè lần trước.
- 11 `*.v2.template.csv`: chỉ header, không chứa giả định về camera thật hoặc annotation đã review.
- `SCHEMA_AND_MIGRATION.vi.md`, `COLLECTION_PROTOCOL.v2.vi.md`, `CALIBRATION_CHECKLIST.vi.md`, `EVALUATION_PROTOCOL.v2.vi.md`: hướng dẫn mới.
- `RESULTS.vi.md`, `protected_before.json`, `integrity_after.json`, `git_status_after.json`: bằng chứng kiểm thử và bảo vệ.

Không có converter migration, runtime ROI importer, appearance extractor, tracker mới hay evaluator AI trong lượt này. Không import source sản phẩm. Không mở camera, database hoặc GPU. Không cài thư viện.

## Chạy kiểm tra trong WSL đã có

Tại /mnt/c/Users/LEGION/Pbl4, environment contacthands Python 3.7:

```bash
/home/legion/miniconda3/envs/contacthands/bin/python -B debug/alert_diagnostics/v4/appearance_preparation/schema_v2/run_schema_checks.py
```

Runner chỉ tạo báo cáo mới trong schema_v2/runs. Tên báo cáo dùng UTC; không phải capture timestamp.

Chỉ kiểm tra một JSON annotation (không ghi file):

```bash
/home/legion/miniconda3/envs/contacthands/bin/python -B debug/alert_diagnostics/v4/appearance_preparation/schema_v2/validate_v2.py debug/alert_diagnostics/v4/appearance_preparation/schema_v2/fixtures/01_no_hand.SYNTHETIC_TEST.json
```

Với annotation thật ở tương lai: thay bằng đường dẫn bundle đã review, thêm `--require-real --asset-root <thu_muc_media_da_duyet>` để đọc kiểm tra file/hash. Không tự đổi SYNTHETIC_TEST thành REAL_CAPTURE. `--require-real` kiểm tra marker, không chứng nhận ground truth hoặc readiness. Asset check không decode video, không xác thực nội dung là video thật.

Nếu jsonschema đã có sẵn, CLI chạy thêm Draft7Validator.check_schema/iter_errors. Môi trường hiện tại thiếu thư viện: formal Draft 7 ghi NOT_AVAILABLE, không tự cài. PASS từ validator riêng không thay thế kiểm định chuẩn đầy đủ.

## Giới hạn

Schema hợp lệ không chứng minh video có nhãn đúng, camera quan sát đủ, TOUCH là chắc chắn hoặc Accuracy đạt yêu cầu. Các giá trị số trong fixtures đều là **SYNTHETIC_TEST**. Test không chạy tracking hoặc nhận diện tay. Accuracy/Precision/Recall/F1 và latency thật: **CHƯA ĐÁNH GIÁ**.

Hoàn thành bước chuẩn bị này thì dừng. Thu camera, thay runtime config, inference hoặc migration annotation cần phê duyệt riêng.
