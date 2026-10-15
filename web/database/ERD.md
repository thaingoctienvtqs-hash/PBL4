# ERD ArtGuard

Database sản phẩm: Microsoft SQL Server. Khóa số nguyên là `IDENTITY`; chuỗi hiển thị tiếng Việt dùng `NVARCHAR`, nội dung dài dùng `NVARCHAR(MAX)`, boolean dùng `BIT`, ngày giờ dùng `DATETIME`.

```mermaid
erDiagram
    ROLES ||--o{ USER_ROLES : grants
    USERS ||--o{ USER_ROLES : has
    LOCATIONS ||--o{ ARTWORKS : displays
    LOCATIONS ||--o{ DEVICES : hosts
    ARTWORKS ||--o{ DEVICES : monitors
    ARTWORKS ||--o{ ALERTS : concerns
    DEVICES ||--o{ ALERTS : detects_demo
    USERS o|--o{ ALERTS : assigned
    ALERTS ||--o{ ALERT_NOTES : has
    USERS ||--o{ ALERT_NOTES : writes
    ALERTS ||--o{ ALERT_HISTORY : tracks
    USERS o|--o{ ALERT_HISTORY : changes
    USERS o|--o{ AUDIT_LOGS : performs
    USERS o|--o{ SYSTEM_SETTINGS : updates
    DEVICES ||--o{ DEVICE_STATUS_HISTORY : records

    USERS { int id PK; nvarchar username UK; nvarchar email UK; nvarchar password_hash; bit is_active }
    ROLES { int id PK; nvarchar name UK }
    USER_ROLES { int user_id PK,FK; int role_id PK,FK }
    LOCATIONS { int id PK; nvarchar code UK; nvarchar name; int capacity; bit is_active }
    ARTWORKS { int id PK; nvarchar inventory_code UK; nvarchar title; nvarchar artist; int location_id FK; nvarchar status }
    DEVICES { int id PK; nvarchar device_code UK; int location_id FK; int artwork_id FK; nvarchar status }
    ALERTS { int id PK; nvarchar event_code UK; int artwork_id FK; int device_id FK; int assigned_user_id FK; nvarchar severity; nvarchar status; nvarchar source }
    ALERT_NOTES { int id PK; int alert_id FK; int user_id FK; nvarchar_max content }
    ALERT_HISTORY { int id PK; int alert_id FK; int user_id FK; nvarchar from_status; nvarchar to_status }
    MODEL_VERSIONS { int id PK; nvarchar name; nvarchar version; bit is_demo }
    SYSTEM_SETTINGS { nvarchar key PK; nvarchar_max value; int updated_by FK }
    AUDIT_LOGS { int id PK; int user_id FK; nvarchar action; nvarchar entity_type; int entity_id }
    DEVICE_STATUS_HISTORY { int id PK; int device_id FK; nvarchar status }
```

## Quyết định schema

- `user_roles` là bảng nối nhiều-nhiều; seed khởi tạo ba role cố định.
- Tác phẩm và thiết bị có thể không còn gắn với khu vực; khóa ngoại dùng `SET NULL` để giữ lịch sử.
- Ghi chú và lịch sử cảnh báo bị xóa cùng cảnh báo; xóa cảnh báo qua API chỉ áp dụng với bản ghi demo.
- `source=demo` và `is_demo=true` phân biệt dữ liệu mô phỏng; không lưu kết quả AI giả.
- Index phục vụ lọc trạng thái, khu vực, thời điểm cảnh báo/audit và mã duy nhất.
- SQLAlchemy `Unicode` được dùng để tạo `NVARCHAR`; các trường nội dung dài dùng `UnicodeText` với biến thể SQL Server `NVARCHAR(MAX)`, không dùng kiểu `NTEXT` cũ.
- Migration ban đầu chỉ tạo bảng thiếu và downgrade không xóa dữ liệu. Kiểm tra SQL Server thật trước khi seed.
