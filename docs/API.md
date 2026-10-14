# API dashboard PBL4

FastAPI bind loopback mặc định ở `127.0.0.1:8000`.

| Method | Route | Ý nghĩa |
|---|---|---|
| `GET` | `/` | Dashboard HTML |
| `GET` | `/health` | API process đang trả lời |
| `GET` | `/status` | Trạng thái worker cùng heartbeat; trạng thái cũ đổi thành `WORKER_NOT_RESPONDING` |
| `GET` | `/history?limit=100&event_type=AI_CONTACT_SUSPECTED_IN_ROI&status=OPEN` | Lịch sử JSON cũ và events SQLite; lọc theo loại/trạng thái, giới hạn tối đa 1000 |
| `GET` | `/frame/latest.jpg` | Ảnh inference mới nhất, `404` trước khi có frame |
| `GET` | `/config` | ROI/ngưỡng/cooldown và cờ URL camera đã cấu hình; không trả URL |
| `POST` | `/config` | Cập nhật `roi`, `thresholds`, `alert` sau khi validate; ghi file JSON nguyên tử |
| `GET` | `/alerts/{filename}` | Evidence ảnh đã lưu |

Body `POST /config` ví dụ:

```json
{
  "roi": {"enabled": true, "coordinates": [0.2, 0.1, 0.8, 0.9], "minimum_bbox_overlap": 0.3},
  "thresholds": {"object_contact": 0.6},
  "alert": {"confirm_frames": 2, "cooldown_seconds": 60}
}
```

ROI chuẩn hóa theo kích thước frame. Các score phải trong `[0,1]`; `x1 < x2`, `y1 < y2`. Camera URL không đổi qua API để tránh lưu IP/mật khẩu vào file cấu hình. `hand_score` không đổi qua API vì model cần được khởi tạo lại; hãy sửa config rồi restart worker.

