# Kết quả Giai đoạn B — ArtGuard v4

Ngày 17/10/2026. Toàn bộ thay đổi mới chỉ dưới debug/alert_diagnostics/v4/.

## Kết quả đã chạy

- Python 3.7.16, Conda contacthands hiện có.
- Preflight source trong RAM: 40/40 PASS, không import torch/cv2/Detectron2.
- Test từ module đã xuất: 40/40 PASS, 0 failure/error, 0.026s.
- 39 dòng tổng hợp so sánh: 13 tình huống × timeout 1/2/3s.
- CLI replay slow_entry PASS, 15 frame được nhận, một event logic.
- Không mở camera, inference GPU, database hoặc sửa môi trường.
- Không tạo ảnh giả hoặc dữ liệu huấn luyện.
- Accuracy/Precision/Recall/F1: CHƯA ĐÁNH GIÁ.

Lệnh test:
```bash
cd /mnt/c/Users/LEGION/Pbl4
/home/legion/miniconda3/envs/contacthands/bin/python -B -m debug.alert_diagnostics.v4.run_tests
```

Artifacts chính:
runs/logic_v4_20261017T034029080685Z_ecbd455a/
  test_summary.json
  comparison_summary.json
  comparison.jsonl
  controlled_inputs.jsonl

Replay CLI:
runs/replay_v4_20261017T034109642350Z_7a8294ab/
  effective_config.json
  frames.jsonl
  summary.json

## So sánh cùng input, cùng timeout 2s

| Tình huống | Event v3 | Event v4 | Diễn giải |
|---|---:|---:|---|
| Đi chậm qua biên | 0 | 1 | V4 bắt entry tích lũy; cả hai cùng một ID |
| Xuất hiện sẵn trong ROI | 0 | 0 | V4 không bỏ gate bảo vệ |
| Tay in sẵn, score 0.99 | 0 | 0 | Không phát thêm ALERT |
| Đi vào rồi đứng yên | 1 | 1 | Một event, giữ cảnh báo |
| Mất detection ngắn | 1 | 1 | V4 xóa history lúc miss, giữ ID, cần bằng chứng mới |
| Mất detection dài | 0 | 0 | Sinh ID mới trong ROI, không kế thừa entry |
| Đi ngang score thấp | 0 | 0 | Không ALERT |
| Một spike OC | 0 | 0 | Không ALERT |
| Score 0.151/0.149 xen kẽ | 1 | 0 | V4 yêu cầu hỗ trợ thời gian; chưa thể gọi là FP đã giảm |
| Fast path >=0.85 | 1 | 1 | Giữ cơ chế nhanh với giới hạn span |
| Nhiều tay, đổi thứ tự | 1 | 1 | V4 giữ ID riêng, không truyền entry cho tay ngoài |
| Frame không đều | 1 | 1 | Cùng giữ ID khi timeout phù hợp |
| Gap 1.01s | 1 | 1 | Cùng timeout 2s thì cả hai giữ một ID |

Với gap 1.01s:
timeout 1s -> v3/v4 đều 6 ID, 0 event.
timeout 2s -> v3/v4 đều 1 ID, 1 event.
timeout 3s -> v3/v4 đều 1 ID, 1 event.
Không gán cải thiện do tăng timeout cho thuật toán v4; chưa biết timeout tối ưu trên camera thật.

Baseline so sánh là hàm update_tracks/advance_track_contact nguyên bản, không phải scheduler file-watch v3.
Input bbox/score được kiểm tra/chuẩn hóa chung trước so sánh. Đây không phải số liệu nhận diện mô hình.

## An toàn và giới hạn

Các test còn kiểm tra:
frame trùng, timestamp bằng/đảo/NaN/Inf, stale frame, clock không nhất quán;
detection sai, score hand thấp, khóa ngưỡng, cache ID đầy;
camera disconnect, missing không tạo bằng chứng, fast pair quá sát;
hungarian assignment có tổng cost tối ưu trong case đối chiếu;
ghép mơ hồ không kế thừa entry, jitter biên, polygon, re-entry episode;
giữ ALERT khi đứng yên, không phát event trùng khi cùng episode được khôi phục.

Timeout 2s trong config là tham chiếu thử nghiệm, không phải tối ưu.
Nhánh duration 0.4s bảo thủ hơn v3, có thể giảm recall với score dao động hoặc chạm ngắn.
Tay thật xuất hiện sẵn trong ROI vẫn có thể bị bỏ lỡ.
Quá lâu không có frame phải ngắt history dù ID còn giữ.
Ghép mơ hồ ưu tiên không truyền nhầm bằng chứng, có thể tăng ID churn.
Camera rung và non-contact có OC cao kéo dài chưa phân biệt chắc chắn bằng bbox/score.
Chưa có adapter v4 tự chạy GPU; run_v4 chỉ replay prediction JSONL.
Source clock/receive time thực tế và latency phải được xác minh trong bước riêng.

## Bảo vệ file gốc

11/11 hash trong protected_before.json khớp test_summary protected_before/protected_after,
gồm mọi worker v3/phiên bản cũ, contact_logic.py, checkpoint,
web/.env.example và web/frontend/package-lock.json.
protected_verification.json ghi đối chiếu cuối.
Không đọc/ghi SQL Server hoặc database runtime, không sửa dataset, không commit/push.
Trạng thái Git đầu/cuối giữ nguyên vì debug/ đã là thư mục untracked từ trước;
các file mới được liệt kê trong protected_verification.json.

Dừng ở Giai đoạn B. Không tự chuyển sang inference thực tế.
