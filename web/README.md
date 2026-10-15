# ArtGuard — website quản lý và bảo vệ tranh

Website gồm dashboard, quản lý bộ sưu tập, phòng trưng bày, thiết bị mô phỏng, cảnh báo và nhật ký xử lý. Camera, thiết bị, sự kiện và phiên bản mô hình hiện là dữ liệu demo; website chưa kết nối camera thật hoặc pipeline AI.

## 1. Kiến trúc

- Frontend: React, TypeScript, Vite, React Router, Axios và Recharts.
- Backend: Python, FastAPI, SQLAlchemy 2, Alembic, Pydantic, JWT và PBKDF2-HMAC-SHA256.
- Database runtime: Microsoft SQL Server qua `mssql+pyodbc`.
- Driver Python: `pyodbc`; ODBC Driver là driver hệ thống riêng, được cấu hình bằng `DB_DRIVER`.
- Frontend gọi REST API ở `/api/v1`; Swagger UI ở `/docs`.
- Access token chỉ giữ trong bộ nhớ tab đang mở.
- SQLite chỉ được dùng trong fixture test biệt lập. Runtime mặc định luôn là SQL Server.

## 2. Cấu trúc

```text
web/
├── backend/app/             # FastAPI, models, API, cấu hình SQL Server
├── backend/migrations/      # Alembic
├── backend/tests/           # API tests SQLite và SQL Server integration opt-in
├── backend/seed_demo.py     # Seed lặp lại an toàn
├── database/ERD.md
├── docs/                    # API và ghi chú phục hồi MySQL cũ
├── frontend/                # React + TypeScript + Vite
├── scripts/                 # PowerShell kiểm tra/cài/chạy
└── .env.example
```

## 3. Yêu cầu

- Windows 10/11 64-bit.
- Python 3.11 trở lên và Python Launcher `py`.
- Node.js 20 trở lên và npm.
- Microsoft SQL Server Database Engine. Trên máy đã kiểm tra, instance mặc định `MSSQLSERVER` đang chạy và nghe TCP 1433.
- Microsoft ODBC Driver for SQL Server tương thích với kiến trúc Python. Máy đã kiểm tra có `ODBC Driver 17 for SQL Server` 64-bit.
- Git để kiểm tra nhánh và trạng thái workspace.

Trạng thái xác minh ngày 14/10/2026: SQL Server default instance `MSSQLSERVER` tại `localhost:1433`, SQL Server 2022 Developer `16.0.1000.6`, ODBC Driver 17 64-bit và Python 64-bit/`pyodbc 5.2.0`. Windows Authentication đã truy vấn thành công qua `sqlcmd` và SQLAlchemy. Tài khoản hiện tại có `sysadmin` và `CREATE ANY DATABASE`; database `pbl4_art_guard` được tạo sau khi xác nhận trước đó database chưa tồn tại. Backend dùng TLS encryption; instance local có chứng thư tự ký nên cấu hình phát triển tin cậy chứng thư local.

Kiểm tra môi trường bằng lệnh chỉ đọc:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\web\scripts\check_environment.ps1
```

Script hiển thị dịch vụ/instance, cổng SQL Server, ODBC Driver, Python, pyodbc và Node/npm; nó không cài phần mềm hoặc thay đổi dịch vụ.

## 4. Xác định SQL Server và ODBC Driver

### Kiểm tra dịch vụ

```powershell
Get-Service MSSQLSERVER -ErrorAction SilentlyContinue
Get-Service -Name 'MSSQL$*' -ErrorAction SilentlyContinue
Test-NetConnection localhost -Port 1433
Get-OdbcDriver -Platform '64-bit' | Where-Object Name -Like '*SQL Server*'
```

Trong SQL Server Configuration Manager, xem `SQL Server Services` để tìm instance; dùng `SQL Server Network Configuration > Protocols for <instance>` để kiểm tra TCP/IP và cổng. Default instance thường dùng cổng 1433. Named instance có thể dùng cổng động; cấu hình `DB_INSTANCE` hoặc cổng TCP thực tế trong `.env`. SQL Server Browser chỉ cần cho cách dò named instance qua mạng.

Kết nối bằng SSMS rồi chạy truy vấn chỉ đọc để xác minh server, version và database:

```sql
SELECT @@SERVERNAME AS server_name,
       SERVERPROPERTY('ProductVersion') AS product_version,
       SERVERPROPERTY('ProductLevel') AS product_level,
       DB_NAME() AS database_name,
       SUSER_SNAME() AS login_name;
```

ODBC Driver cài trên hệ điều hành và thư viện Python `pyodbc` là hai thành phần riêng. `setup_backend.ps1` cài `pyodbc` trong virtualenv theo requirements; không cài ODBC Driver Windows. `DB_DRIVER` phải khớp chính xác tên hiển thị trong ODBC Data Sources/`Get-OdbcDriver` và cùng kiến trúc 64-bit với Python.

## 5. Tạo database và cấp quyền

Trước khi chạy script, kết nối đúng instance bằng SSMS và xác nhận database chưa tồn tại. Script dưới đây chỉ tạo `pbl4_art_guard` khi chưa có; không xóa hay ghi đè database hiện hữu:

```sql
IF DB_ID(N'pbl4_art_guard') IS NULL
    EXEC(N'CREATE DATABASE [pbl4_art_guard]');
```

Đăng nhập tạo database cần quyền `CREATE ANY DATABASE` hoặc quyền quản trị tương ứng. Nếu không có quyền, nhờ quản trị viên SQL Server chạy script; không nâng quyền tài khoản ứng dụng.

Ưu tiên Windows Authentication. Khi chạy backend thủ công, SQL Server nhận dạng chính tài khoản Windows chạy tiến trình backend. Trong SSMS, tạo login cho đúng tài khoản Windows và user tương ứng trong `pbl4_art_guard`; dùng role `db_datareader` và `db_datawriter` cho runtime.

Trong SSMS: vào `Security > Logins > New Login`, chọn Windows Authentication hoặc SQL Server Authentication; ở `User Mapping`, ánh xạ login tới `pbl4_art_guard` và chọn `db_datareader`, `db_datawriter`. Với SQL Authentication, bật chế độ mixed authentication chỉ khi chính sách máy cho phép; đặt mật khẩu trực tiếp trong SSMS, không lưu script chứa mật khẩu vào Git. Không dùng `sa` làm tài khoản ứng dụng.

Tài khoản runtime chỉ cần đọc/ghi dữ liệu. Khi phải chạy Alembic bằng chính login ứng dụng, tạm cấp quyền DDL dưới đây trong database đích rồi thu hồi ngay sau khi migration thành công:

```sql
USE [pbl4_art_guard];
GRANT CREATE TABLE TO [pbl4_app];
GRANT ALTER ON SCHEMA::dbo TO [pbl4_app];
-- Sau migration:
REVOKE ALTER ON SCHEMA::dbo FROM [pbl4_app];
REVOKE CREATE TABLE FROM [pbl4_app];
```

## 6. Cấu hình `.env`

Tạo `.env` chỉ khi chưa có. Lệnh dưới đây không ghi đè tệp hiện có:

```powershell
if (-not (Test-Path .\web\.env)) { Copy-Item .\web\.env.example .\web\.env }
```

Cập nhật `web/.env` theo đúng instance và driver trên máy:

```env
DB_BACKEND=mssql
DB_SERVER=localhost
# SQL Server default instance is the MSSQLSERVER service; leave DB_INSTANCE empty.
DB_INSTANCE=
DB_PORT=1433
DB_NAME=pbl4_art_guard
DB_DRIVER=ODBC Driver 17 for SQL Server
DB_TRUSTED_CONNECTION=true
DB_USERNAME=
DB_PASSWORD=
DB_ENCRYPT=true
# Local development only: trust this instance's self-signed certificate.
DB_TRUST_SERVER_CERTIFICATE=true
```

- Windows Authentication: để `DB_TRUSTED_CONNECTION=true`, `DB_USERNAME` và `DB_PASSWORD` trống; cấp quyền cho đúng tài khoản Windows chạy backend.
- SQL Server Authentication: đặt `DB_TRUSTED_CONNECTION=false`, nhập `DB_USERNAME`/`DB_PASSWORD` trong `.env`. Không commit `.env`.
- Với named instance, điền `DB_INSTANCE=<tên instance>`; `DB_INSTANCE` sẽ được ưu tiên thay cho `DB_PORT`.
- Giữ `DB_ENCRYPT=true`. Default instance `MSSQLSERVER` được truy cập tại `localhost:1433`; để `DB_INSTANCE` trống. `DB_TRUST_SERVER_CERTIFICATE=true` chỉ dùng cho SQL Server local có chứng thư tự ký; production phải cài chứng thư hợp lệ và để `false`.
- Đặt `JWT_SECRET_KEY` thành chuỗi ngẫu nhiên riêng trước khi chia sẻ hoặc triển khai.

## 7. Cài backend và chạy migration

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\web\scripts\setup_backend.ps1
```

Cài cả công cụ test:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\web\scripts\setup_backend.ps1 -WithTests
```

Sau khi SQL Server, database và quyền truy cập đã được xác minh, chạy migration:

```powershell
Push-Location .\web\backend
try { & .\.venv\Scripts\python.exe -m alembic upgrade head } finally { Pop-Location }
```

Migration `0001_initial_schema` tạo bảng còn thiếu bằng metadata và `checkfirst=True`; downgrade không xóa dữ liệu. Không chạy `DROP DATABASE`, reset schema hoặc import dữ liệu MySQL lên database đang dùng. Bản migration hiện có được giữ nguyên vì chưa xác định được nó đã áp dụng trong database cũ hay chưa.

## 8. Seed dữ liệu demo

Chạy sau khi migration thành công:

```powershell
Push-Location .\web\backend
try { & .\.venv\Scripts\python.exe .\seed_demo.py } finally { Pop-Location }
```

Seed nhận diện bản ghi bằng khóa ổn định, bổ sung dữ liệu còn thiếu và không xóa bảng. Nó tạo roles, tài khoản demo, khu vực, tác phẩm, thiết bị mô phỏng, cảnh báo demo, lịch sử xử lý, phiên bản mô hình và system settings. Mật khẩu được băm; log chỉ in số lượng, không in mật khẩu. Chỉ đăng nhập demo sau khi lệnh seed kết thúc thành công. Các tài khoản demo phải được thay/khóa trước khi triển khai.

## 9. Chạy backend, frontend và API

Trong một cửa sổ PowerShell:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\web\scripts\run_backend.ps1
```

Trong cửa sổ thứ hai:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\web\scripts\setup_frontend.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\web\scripts\run_frontend.ps1
```

- Website: `http://127.0.0.1:5173`
- API: `http://127.0.0.1:8000/api/v1`
- Swagger/OpenAPI: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/health`

Health trả `503 degraded` khi database không kết nối được. Backend không tự tạo database, không chuyển sang SQLite và không khởi động/dừng SQL Server.

## 10. Tính năng website

- Đăng nhập JWT, thông tin tài khoản và phân quyền `admin`, `manager`, `operator`.
- Dashboard SQL Server, báo cáo xu hướng và phân bố cảnh báo.
- CRUD khu vực, tác phẩm, thiết bị, người dùng, phiên bản mô hình và cài đặt.
- Tải ảnh JPEG/PNG/WebP tối đa 5 MB cho tác phẩm; có xem trước, thay ảnh và ảnh thu nhỏ trong danh sách. Backend kiểm tra nội dung ảnh, đặt tên tệp ngẫu nhiên và lưu tệp trong `backend/uploads/artworks/`; SQL Server chỉ lưu đường dẫn tương đối ở `artworks.image_url`. Thư mục ảnh bị Git bỏ qua.
- Quản lý cảnh báo, ghi chú, lịch sử trạng thái và audit log.
- Camera/thiết bị/cảnh báo demo vẫn là dữ liệu mô phỏng; không thay đổi hoặc giả lập kết quả AI.

API tải ảnh: `POST /api/v1/artworks/{artwork_id}/image` với multipart field `file`. Chỉ `admin` và `manager` được tải hoặc thay ảnh. Ảnh mới được xác thực và lưu trước khi cập nhật bản ghi; nếu lưu database thất bại, ảnh hiện tại vẫn được giữ. Ảnh cũ do tính năng này quản lý chỉ được xóa sau khi thay thế thành công. Không cần migration vì cột `image_url` đã có trong schema hiện tại.

## 11. Kiểm tra

Chạy backend tests, TypeScript và production build:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\web\scripts\run_tests.ps1
```

Test API thông thường dùng SQLite `:memory:` trong fixture biệt lập; không dùng SQLite thay cho integration. Bài kiểm tra SQL Server thật kết nối trực tiếp `pbl4_art_guard`, đăng nhập tài khoản demo, tạo/đọc/cập nhật/xóa dữ liệu riêng có mã `IT-*` cho khu vực, tranh, thiết bị và cảnh báo, rồi gọi dashboard và báo cáo. Bài kiểm tra ảnh xác minh quyền truy cập, loại ảnh sai, giới hạn 5 MB, lưu/đọc lại `image_url` từ SQL Server, phục vụ ảnh và thay ảnh an toàn. Các bản ghi kiểm thử sẽ được dọn sau khi chạy; audit log vẫn được giữ lại. Cần đặt `RUN_SQLSERVER_INTEGRATION=1` để chạy:

```powershell
$env:RUN_SQLSERVER_INTEGRATION = '1'
$env:DB_TRUST_SERVER_CERTIFICATE = 'true' # Chỉ cho SQL Server local có chứng thư tự ký.
Push-Location .\web\backend
try { & .\.venv\Scripts\python.exe -m pytest -q tests\test_sqlserver_integration.py } finally { Pop-Location }
Remove-Item Env:RUN_SQLSERVER_INTEGRATION, Env:DB_TRUST_SERVER_CERTIFICATE -ErrorAction SilentlyContinue
```

## 12. Xử lý lỗi kết nối

- `Data source name not found` hoặc `Can't open lib`: xác minh `DB_DRIVER` trùng tên ODBC Driver đã cài và kiến trúc driver khớp Python.
- `Login failed`: xác minh mode xác thực, login/user và quyền trong `pbl4_art_guard`; không dùng thông tin `root` của MySQL.
- `target principal name is incorrect` / `Cannot generate SSPI context`: Windows Authentication chưa xác thực được principal. Kiểm tra đúng tài khoản Windows, SPN/Kerberos và cấu hình instance bằng SSMS; nếu dùng SQL Authentication, chỉ chuyển khi đã có credential hợp lệ.
- `certificate chain was issued by an authority that is not trusted`: giữ `DB_ENCRYPT=true`; cài chứng thư tin cậy hoặc chỉ đặt `DB_TRUST_SERVER_CERTIFICATE=true` trong phát triển local.
- `database unavailable`: xác minh service, instance/port, TCP/IP, database, ODBC Driver và các biến `DB_*` mà không in mật khẩu ra log.
- `Invalid object name`: chạy `alembic upgrade head` sau khi kết nối database thành công.
- Frontend báo mất kết nối: xác minh backend ở cổng 8000 và SQL Server health.

## 13. Dữ liệu MySQL/XAMPP cũ

Ứng dụng runtime không còn phụ thuộc MySQL/MariaDB, PyMySQL hay XAMPP. Việc chuyển backend không tự nhập dữ liệu từ MySQL. Ghi chú về bản sao XAMPP cũ, tính chất của bản sao và nguyên tắc phục hồi nằm trong [docs/legacy-mysql-recovery.md](docs/legacy-mysql-recovery.md). Không ghi đè bản sao dữ liệu cũ.

## 14. Tài liệu

- [API](docs/API.md)
- [ERD và quyết định schema SQL Server](database/ERD.md)
- [Ghi chú phục hồi XAMPP/MySQL cũ](docs/legacy-mysql-recovery.md)
