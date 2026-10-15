# Ghi chú phục hồi MySQL/XAMPP cũ

Tài liệu này chỉ lưu thông tin lịch sử phục vụ điều tra và phục hồi dữ liệu cũ. Backend hiện tại dùng SQL Server; không cần XAMPP để chạy website. Không xóa hoặc ghi đè thư mục sao lưu nêu dưới đây.

## Trạng thái được ghi nhận ngày 14/10/2026

- Hai cây cài đặt từng tồn tại tại `C:\xampp` và `D:\xampp`; registry chỉ nhận diện bộ cài tại `C:\xampp`.
- Cấu hình MySQL trong cả hai cây trỏ tới `C:\xampp\mysql\data`.
- MySQL PID 3104 không hoàn thành handshake với `mysqladmin shutdown`; tiến trình đó được dừng cưỡng bức sau khi người dùng xác nhận.
- Apache PIDs 5424 và 20472 được kiểm tra đúng binary `C:\xampp\apache\bin\httpd.exe`, sau đó dừng theo xác nhận riêng. Cổng 80 và 443 đã đóng khi kiểm tra.
- `C:\xampp\uninstall.exe` lỗi `0xc0000142` khi chạy có và không có elevation. Không có thay đổi gỡ cài đặt; cả hai cây XAMPP còn tồn tại ở lần kiểm tra cuối.
- Không xác minh được schema `pbl4_art_guard` hoặc trạng thái migration ở MySQL cũ vì kết nối MySQL không hoạt động.

## Bản sao được bảo vệ

Thư mục `D:\PBL4_XAMPP_BACKUP\20261014-121152448` chứa bản sao vật lý các datadir MySQL của hai cây XAMPP cùng `htdocs`, cấu hình Apache/PHP/phpMyAdmin và manifest SHA-256. Tại thời điểm tạo, các tệp được đối chiếu theo đường dẫn, kích thước và hash.

Đây là bản sao vật lý crash-consistent được tạo sau khi tiến trình MySQL bị dừng cưỡng bức. Nó không phải SQL dump, chưa được thử khôi phục và không chứng minh dữ liệu database nhất quán. `web/.env` không tồn tại lúc tạo bản sao nên không được sao chép.

Không dùng bản sao này để ghi đè thư mục `data` của một cài đặt mới, không xóa và không sửa bản sao gốc. Chuyển backend sang SQL Server không nhập dữ liệu MySQL. Nếu sau này cần phục hồi, trước tiên tạo bản sao làm việc riêng; chỉ dùng một quy trình phục hồi đã được xác minh trên bản sao đó.

## Lịch sử migration

Không có database cũ truy vấn được để xác định revision Alembic đã áp dụng. Revision `0001_initial_schema` vì vậy được giữ nguyên; không reset lịch sử và không chạy downgrade để xóa bảng.
