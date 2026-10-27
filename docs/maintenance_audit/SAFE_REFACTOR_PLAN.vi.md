# ArtGuard — Kế hoạch thay đổi nhỏ và bảo vệ hiện trạng

Ngày 18/10/2026. **Chỉ Nhóm 1 được phê duyệt và thực hiện: tạo sáu tài liệu mới.** Các nhóm dưới đây là đề xuất, phải chờ phê duyệt cụ thể; không tạo worker/AI mới, không dọn file trong lượt này.

## Mốc Git và vùng bảo vệ

- Root: `C:/Users/LEGION/Pbl4`.
- Nhánh trước tài liệu hóa: `test-web`.
- HEAD: `aca33ee901bd12f527499c20222100b104d0d6b1`.
- Hai file tracked đã sửa trước: `web/.env.example`, `web/frontend/package-lock.json`; giữ nguyên.
- Nhiều file untracked đã có sẵn, gồm debug, worker compat/v3, geometry/contact_logic, data/evidence và ảnh. **Untracked không có nghĩa được phép xóa.**
- `docs/maintenance_audit/` đã kiểm tra chưa tồn tại trước khi tạo. Chỉ tạo file ở chế độ exclusive, không ghi đè.
- Repo gốc `C:/Users/LEGION/PaintingProtection/ContactHands`, checkpoint, dataset thật ngoài PBL4, SQL Server và môi trường không phải đích chỉnh sửa.

Các lệnh Git chỉ đọc dùng ghi nhận trước/sau:

~~~powershell
git --no-optional-locks status --short
git --no-optional-locks branch --show-current
git --no-optional-locks rev-parse HEAD
~~~

Không dùng stash/reset/restore/clean để tạo trạng thái “sạch”; không commit/push. Git Windows là mốc so sánh, xem [môi trường](ENVIRONMENTS.vi.md).

## Mốc toàn vẹn trước khi tạo tài liệu

Checksum được giữ trong bộ nhớ phiên làm việc, không tạo manifest vào source hay artifacts cũ:

| Phạm vi | Mốc trước |
|---|---|
| SHA-256 nội dung file dự án | 1.155 file; loại .git, dependencies cài sẵn, bytecode/build, DB và secret khỏi băm nội dung |
| SHA-256 tổng hợp nội dung | `492c61a6c8126fe5c7df44b3123ee7ff6bc0b3274bbea6cc975f4e9defa12ffd` |
| Metadata toàn bộ file ngoài .git và thư mục tài liệu mới | 15.322 file, gồm dependencies/cache/DB; kích thước + mtime_ns |
| SHA-256 tổng hợp metadata | `2a92c3ac063816a1b04b1885be7a4ddd49463f3eb4dad20a819285654e92ab50` |
| Checkpoint chính | `c03f38a947d426b39b7538a5478f823799d98b34e0fb299ec35a6520342a342a` |
| Lỗi truy cập / symlink gặp trong lượt quét | 0 / 0 |

DB SQLite hiện có được theo dõi metadata, **không mở kết nối hoặc băm nội dung DB**; secrets không được đọc. Dataset ContactHands thật ngoài repo không được duyệt/băm lại. Vì vậy báo cáo không được nói đã hash toàn bộ dữ liệu trên máy. Git internal metadata cũng không thuộc tập kiểm kê. Sau khi tạo tài liệu, đối chiếu cùng phạm vi, thêm kiểm tra Git và đúng sáu file mới. Kết quả sau được báo trong phần trả lời hoàn tất; bảng này là mốc trước.

## Thứ tự thay đổi đề xuất

| Nhóm / thứ tự | Thay đổi có thể đề xuất | Điều kiện và phép kiểm tra trước khi chấp thuận |
|---|---|---|
| 1 — hiện tại | Sáu tài liệu kiến trúc/entrypoint/môi trường/phụ thuộc/ứng viên/kế hoạch | Chỉ tạo mới, kiểm tra link/path/CLI tĩnh; không chạy runtime |
| 2a — nhỏ nhất | Một import local không dùng: `os` trong inference/dataset_collector.py | Xác nhận không export/dynamic use; patch đúng một dòng; AST và test cô lập không camera; xin duyệt trước |
| 2b — độc lập | Các import dư khác, từng file một | Không chạm registry, runtime setup, migration models; đối chiếu API/module exports |
| 3 | Chuẩn hóa mô tả launcher hoặc tạo launcher riêng sau khi thống nhất luồng | Xác nhận Windows/WSL, producer duy nhất, cổng, ROI/config/output; không sửa launcher cũ trong Nhóm 1 |
| 4 | Contract tường minh cho config, prediction, stability, entry/temporal | Giữ v3 và Phase D/E/F đối chứng; test công khai mismatch; không đổi ngưỡng để ép ALERT |
| 5 | Bridge AI event → FastAPI → SQL Server và evidence | Phê duyệt riêng, backup DB hợp lệ, auth/ID/idempotency/mapping timestamp; test sandbox trước |
| 6 | Xem xét gom/archive các worker chuyển tiếp | Inventory caller trong/ngoài repo, owner đồng ý, restore drill; không mặc định xóa duplicate |
| 7 | Dọn artifacts/bytecode/dependencies nếu thật sự cần | Chính sách retention và backup xác minh; tuyệt đối không trộn với source refactor |

Không đề xuất đổi kiến trúc tracking/recovery trong Nhóm 2a. Geometry F vẫn opt-in; các phản ví dụ FAIL phải được giữ như bằng chứng chất lượng.

## Backup và rollback trước mỗi nhóm sau

1. Chốt danh sách file được phép sửa, hash, trạng thái staged/unstaged/untracked và owner; nếu file đang có thay đổi, yêu cầu phạm vi patch rõ ràng.
2. Sau khi được duyệt vị trí backup, tạo bản sao **mới**, có timestamp/ID duy nhất, kiểm tra không tồn tại và xác minh hash. Nhóm 1 không tạo backup ngoài sáu tài liệu.
3. Không copy secret vào Git/tài liệu; không sao chép trực tiếp SQLite đang ghi như cách backup chuẩn. SQL Server chỉ backup/restore theo quy trình được quản trị viên duyệt riêng.
4. Giữ patch nhỏ, một mục tiêu; đối chiếu diff trước khi test. Không autoformat, sửa newline/LFS hoặc thay lockfile ngoài phạm vi.
5. Nếu lỗi, dừng và trình patch hoàn tác giới hạn đúng thay đổi của nhóm. Không reset/restore/stash để hoàn tác cả file có sửa trước; rollback cũng cần giữ phần thay đổi của người dùng.
6. Chỉ báo hoàn thành khi integrity checks và regression phù hợp có bằng chứng. Không bỏ/đổi kỳ vọng test FAIL để làm xanh.

## Ma trận regression an toàn cho lượt sau

| Phép kiểm tra | Điều kiện / giới hạn |
|---|---|
| AST Python, cú pháp TS/JSON, local links, diff phạm vi | Ưu tiên parser không import; Python `-B`; xác nhận parser phù hợp phiên bản mục tiêu |
| Unit test logic được liệt kê cụ thể | Đọc test trước, guard filesystem/network/DB/model; output mới được duyệt, không ghi vào phase cũ |
| So sánh D/E/F | Cùng prediction JSONL, timeout, ROI, threshold; giữ expected failures; phân biệt event/track identity |
| Website typecheck/API tests | Chỉ sau duyệt: đảm bảo không SQL thật, upload/evidence thật; typecheck không đồng nghĩa UI/runtime hoạt động |
| Camera/GPU | Phê duyệt riêng; một consumer chính; ROI hiệu chuẩn; thời gian/VRAM và output riêng |
| SQL Server/integration | Phê duyệt riêng, sandbox/backup/rollback và hợp đồng chống trùng; không migration/seed tự động |

**Không chạy toàn bộ pytest.** [tests/test_contacthands.py](../../tests/test_contacthands.py), dòng 12/21 tạo model/inference khi import. Backend app tạo upload directories khi import; YOLO entrypoint tạo runtime paths trước main. Một lệnh “chỉ collect” hoặc `--help` có thể vẫn làm thay đổi trạng thái. Xem [DEPENDENCIES](DEPENDENCIES.vi.md).

[Kết quả F đã lưu](../../debug/alert_diagnostics/v4/phase_f/RESULTS.vi.md) ghi 308 PASS/8 FAIL/0 ERROR trên 316 test duy nhất; đây là **báo cáo lịch sử**, không phải kết quả chạy lại Nhóm 1. Những gate identity/recovery chưa đạt không được xóa hoặc gọi là regression mới chỉ vì còn đỏ.

## Tiêu chí dừng ngay

- Target tài liệu hoặc file dự kiến đã tồn tại trước khi ghi.
- File ngoài phạm vi thay đổi hash/metadata không giải thích được, branch/HEAD thay đổi hoặc xuất hiện diff bất ngờ.
- Test import model, mở camera/network, ghi evidence/DB/phase được bảo vệ.
- Muốn sửa config thực tế, threshold, checkpoint, dataset, môi trường, migration hoặc source chưa được duyệt.
- Không phân biệt được identity/stability/contact: giữ UNKNOWN/UNCERTAIN và báo giới hạn, không truyền history để ép ALERT.
- Lệnh bị chặn quyền: nêu chính xác thao tác và lý do, không tìm đường vòng thay đổi dữ liệu.

## Điều kiện đánh giá chất lượng ArtGuard

Thu video camera OV3660 đúng mép trên tranh, nhìn xiên xuống; đo FOV/coverage/vùng mù và sai số đồng bộ, raw frames không overlay, nhãn có nguồn xác minh TOUCH/NEAR_NO_TOUCH/NO_TOUCH/UNKNOWN. Chia validation/test theo phiên/capture group, khóa tham số trước test. Báo Accuracy, Precision/Recall/F1, confusion matrix, abstention/UNKNOWN, coverage, false alerts/hour và contact→ALERT latency.

Mục tiêu >80% Accuracy và ≥80% Precision/Recall/F1 hiện **CHƯA ĐÁNH GIÁ**. Mốc dưới 500 ms là mong muốn cần đo; không đồng nhất thời gian inference với độ trễ cảnh báo tổng, không đánh đổi an toàn để đạt mốc.

**Bước đề xuất tiếp theo duy nhất:** xin duyệt Nhóm 2a, kiểm tra và bỏ một import `os` không dùng tại [dataset_collector.py](../../inference/dataset_collector.py), dòng 5, với static check và regression logic cô lập. Dừng sau Nhóm 1; chưa thực hiện bước này.
