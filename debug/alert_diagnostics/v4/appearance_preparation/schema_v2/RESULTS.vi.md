# Kết quả chuẩn bị annotation v2

## Kiểm thử đã chạy

- Python WSL contacthands: 3.7.16; dùng -B, không tạo bytecode.
- Lần đầu: 98 test, 97 PASS / 1 FAIL / 0 ERROR. Lỗi half_resolution: camera dùng definition nội tuyến, chưa nhận ràng buộc hai chiều cùng có hoặc cùng null. Đã sửa tham chiếu schema mới, không đổi kỳ vọng test.
- Lần tiếp theo: 98/98 PASS.
- Sau bổ sung bốn regression test: **102/102 PASS, 0 FAIL, 0 ERROR, 0 SKIP**.
- Runner parse AST các Python mới và parse JSON mới; 11 CSV chỉ header được test khớp schema.
- 12 fixture JSON đánh dấu SYNTHETIC_TEST: 11 expected-valid, 1 deliberately invalid thiếu video_id; fixture sai được từ chối đúng. Không tạo ảnh/video.
- CLI no-hand: exit 0, PASS.
- CLI --require-real với SYNTHETIC_TEST: exit 1, từ chối đúng kỳ vọng.
- CLI thiếu video_id: exit 1, từ chối đúng kỳ vọng.
- formal Draft 7/jsonschema: **NOT AVAILABLE / NOT TESTED**; không cài thêm. PASS là checker cho tập keyword schema này và semantic validation, không phải chứng nhận chuẩn Draft 7.
- AI accuracy/precision/recall/F1/false alerts/latency và camera thật: **CHƯA ĐÁNH GIÁ**.

Các run JSON được giữ riêng trong runs/, có cả báo cáo FAIL ban đầu. Tên run dùng UTC. Các ca hai tay/entry/occlusion là test annotation, **không kiểm thử tracking hay contact model**.

## Bảo vệ

Đã đọc lại hash: 1094/1094 file PBL4 trong snapshot không thay đổi; 7/7 file mẫu external ContactHands không đổi. Chi tiết integrity_after.json. Đây không phải hash toàn bộ dataset external. Không mở/hash database. Không truy cập để sửa repo ContactHands gốc.

Git status trước/sau khớp; debug/ vốn đã untracked nên short status không liệt kê từng file mới. Danh sách mới nằm trong git_status_after.json. git diff --check exit 0, có cảnh báo LF/CRLF sẵn ở src/services/alert.py; không chỉnh file đó.

Không sửa v3/v4/C/D/E/F, source sản phẩm, checkpoint, annotation/dataset cũ, CUDA/Conda/Detectron2, SQL Server hoặc frontend. Không camera/GPU/training, không migration thật, không commit/push.

## Giới hạn và bước dừng

Chưa triển khai runtime ROI converter, evaluator AI, appearance feature/recovery, calibration UI hoặc capture tool. Chưa có formal schema validation, video thật v2 và kiểm chứng metadata/GT. Xem SCHEMA_AND_MIGRATION.vi.md và EVALUATION_PROTOCOL.v2.vi.md về giới hạn.

Giữ các giá trị góc/FOV/coverage chưa đo ở null/UNKNOWN trong annotation thật. Chỉ có số giả lập trong fixtures SYNTHETIC_TEST. Checklist hiệu chuẩn và kế hoạch 12 phiên là hướng dẫn, chưa thực hiện và chưa chứng minh đủ dữ liệu để đạt 80%.

Dừng sau chuẩn bị schema/tài liệu; chưa tự chuyển sang thu video hoặc AI.
