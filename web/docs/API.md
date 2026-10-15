# API overview

Prefix: `/api/v1`. Hầu hết endpoint yêu cầu `Authorization: Bearer <access_token>`; `/auth/login` là endpoint đăng nhập duy nhất công khai. Token trả về hết hạn sau thời lượng ở `JWT_EXPIRE_MINUTES`; frontend giữ token trong bộ nhớ.

Backend runtime dùng SQL Server qua SQLAlchemy `mssql+pyodbc`. SQLite chỉ được dùng trong test API cô lập; API không đổi database dự phòng khi SQL Server lỗi. `GET /health` thực hiện truy vấn kiểm tra kết nối và trả `503 degraded` nếu database không sẵn sàng.

| Nhóm | Endpoint chính | Phân quyền ghi |
|---|---|---|
| Auth | `POST /auth/login`, `GET /auth/me`, `POST /auth/logout` | Đăng nhập cần thông tin hợp lệ |
| Dashboard | `GET /dashboard?days=7`, `GET /reports/summary?days=30` | Chỉ đọc; truy vấn DB |
| Locations | `GET/POST /locations`, `PATCH/DELETE /locations/{id}` | Admin/manager; xóa admin |
| Artworks | `GET/POST /artworks`, `GET/PATCH/DELETE /artworks/{id}`, `GET /artworks/{id}/alerts` | Admin/manager; xóa admin |
| Devices | `GET/POST /devices`, `PATCH/DELETE /devices/{id}` | Admin/manager; xóa admin |
| Alerts | `GET/POST /alerts`, `PATCH /alerts/{id}/status`, notes, history | Admin/manager tạo; mọi role cập nhật trạng thái và ghi chú |
| Users/Roles | `GET /roles`, `GET/POST /users`, `PATCH /users/{id}` | Admin |
| Models | `GET /models`, `PATCH /models/{id}/status` | Admin/manager đổi metadata |
| Settings | `GET /settings`, `PUT /settings/{key}` | Admin thay đổi; admin/manager đọc |
| Audit | `GET /audit-logs` | Admin |

Danh sách trả `{items,total,page,page_size}`. API không trả password hash, JWT secret hoặc token trong audit log. Sai dữ liệu trả 422; thiếu xác thực 401; thiếu quyền 403; không thấy bản ghi 404; xung đột mã/email 409.
