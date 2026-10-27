# ALERT diagnostics độc lập

Bộ này dùng nguyên hàm update_tracks/advance_track_contact và _analyze_frame của worker v3.
Không sửa source sản phẩm; không có camera client hoặc SQL Server client.
Import/test/help không tải cv2, torch, Detectron2, checkpoint hoặc khởi tạo database.
Python 3.7 trở lên; chỉ thư viện chuẩn cho test logic.

## Chạy logic (được phép trong giai đoạn này)

```bash
cd /mnt/c/Users/LEGION/Pbl4
/home/legion/miniconda3/envs/contacthands/bin/python -B debug/alert_diagnostics/run_logic_tests.py
```

Nếu interpreter Conda không dùng được, /usr/bin/python3 chạy được test logic.
Kết quả nằm trong runs/logic_<UTC>_<random>/:
summary.json, logic_frames.jsonl, timeout_sweep.json, logic_only.sqlite3.
Database dùng loại sự kiện CONTROLLED_LOGIC_TEST_NOT_AI; không có ảnh giả hoặc dữ liệu train.
PASS là khớp hành vi hiện tại, kể cả tái hiện việc CANDIDATE bị chặn, không phải mọi tình huống đều lên ALERT.
Các tọa độ/score kiểm soát chỉ là đầu vào hàm, không phải prediction thực.

A: xuất hiện sẵn trong ROI; B: đi vào rồi giữ; C: bước di chuyển dưới ngưỡng mỗi frame;
D: timeout; E: 3/5; F: 2 frame >=0.85 sau entry; G: tay tĩnh trong tranh.
Test bổ sung kiểm tra score thấp, mất detection, bảo vệ output, biến môi trường và instrumentation.
Không xóa điều kiện entry để ép test PASS.

## Cấu hình

config.baseline.json là ROI THỬ NGHIỆM [0.4,0.1,0.8,0.9], chưa hiệu chuẩn theo tranh.
Dùng shape=rectangle, normalized=true (boolean), coordinates gồm 4 số.
Giữ nguyên ngưỡng ContactHands, timeout=1 giây và temporal defaults.
Runner nạp config tường minh, từ chối các override môi trường PBL4/ContactHands liên quan,
và thay toàn bộ output bằng đường dẫn tuyệt đối dưới run mới.
Đường dẫn UNSTARTED trong template không được runner dùng để ghi.
Không chạy worker v3 trực tiếp với template; dùng runner chẩn đoán.

## Inference thực tế: CHƯA CHẠY, cần phê duyệt riêng

Runner chỉ đọc JPEG đã có. Không tự capture hoặc khởi động thêm ESP32 stream.
Dùng một tiến trình thu ảnh đã được duyệt; không chạy thêm nguồn capture.
Mỗi lần chạy tạo thư mục mới, SQLite mới, JSONL mới và preview riêng cho từng frame.
Nếu nguồn ảnh không đổi, runner không infer lại ảnh đó.
Đồng bộ CUDA trước/sau predict để đo inference; log này vẫn không phải độ trễ vật lý từ camera.
Giới hạn được kiểm tra giữa các lời gọi; model initialization/native GPU call đang treo không thể
bị deadline Python ngắt ngay. Có thể dùng timeout của Linux để chặn ngoài tiến trình.
Warm-up có thể làm frame đầu chậm; lưu dữ liệu thô, không tự bỏ mẫu.
Không tự tải second-stream weights; yêu cầu cache local đã có.
ROI thử nghiệm không đủ để chứng minh tiếp xúc thật hoặc độ chính xác mô hình.

Chuẩn bị WSL hiện có (không cài thư viện):

```bash
cd /mnt/c/Users/LEGION/Pbl4
source /home/legion/miniconda3/etc/profile.d/conda.sh
conda activate contacthands
export CUDA_HOME=/usr/local/cuda-11.7
export LD_LIBRARY_PATH=/usr/lib/wsl/lib:/usr/local/cuda-11.7/lib64:${LD_LIBRARY_PATH:-}
export TORCH_CUDA_ARCH_LIST=8.6
```

Lệnh baseline CHỈ chạy sau khi được phê duyệt inference:

```bash
timeout --signal=INT --kill-after=10s 180s python -B debug/alert_diagnostics/run_inference.py \
  --allow-inference --config-json debug/alert_diagnostics/config.baseline.json \
  --frame-file /mnt/c/Users/LEGION/Pbl4/data/camera_frame.jpg \
  --device cuda --poll-interval 0.5 --max-frames 30 --max-seconds 120
```

Một lần so sánh độc lập (cần duyệt) có thể thêm --track-timeout 3.
Giá trị 2 và 3 giây chỉ là ứng viên, không phải tối ưu đã đo.
Chọn timeout lớn hơn phân vị cao của tracking_delta_seconds cộng biên dao động.
Timeout dài có thể ghép nhầm tay; không tăng tùy tiện đến khi có ALERT.
Tránh chạy hai runner hoặc production worker cùng GPU.

frames.jsonl ghi timestamp UTC, mtime và SHA256 input, inference_seconds,
frame_processing_seconds, tracking_monotonic_seconds, tracking_delta_seconds,
expired_track_ids; mỗi track có ID/new_track, entry, OC, overlap, positive_frames,
history, fast streak, state, state_reason và alert_blockers.
alert_blockers liệt kê từng gate; window và fast path là hai lựa chọn thay thế,
không phải bắt buộc cùng đạt. Track không quan sát được giữ score gần nhất và observed=false.
runtime.jsonl ghi môi trường, model init, ảnh hỏng, nguồn mất/stale, lỗi.
events.sqlite3 chứa sự kiện thử từ AI; evidence/ và frames/ đều thuộc run riêng.
summary.json kết thúc có số frame/lỗi/hash source.
Nếu bị SIGKILL, JSONL đã flush có thể còn; summary có thể chưa được tạo.

## Hướng sửa sau khi đủ số liệu

Không bỏ ever_entered_roi. Đánh giá cách ghi entry từ quỹ đạo tích lũy qua hai vùng
ngoài/trong có hysteresis, thay vì yêu cầu một bước vượt biên đủ lớn.
Track sinh sẵn trong ROI cần chính sách riêng có nhiều bằng chứng theo thời gian;
chuyển động/OC chỉ là nghi vấn, không chứng minh đó là tay thật.
Tay in sẵn cần baseline hoặc bằng chứng độc lập và đánh giá video có nhãn.
Nếu mất track gây lỗi, thử timeout phù hợp tốc độ xử lý trước khi sửa entry.
Không tính precision/recall/FPR/độ trễ thực tế khi chưa có video nhãn và phép đo phù hợp.

Bản UTF-8 chính thức: README.vi.md. RESULTS.vi.md ghi kết quả và danh sách artifacts. Các bản .md ban đầu được giữ nguyên theo nguyên tắc không ghi đè.
