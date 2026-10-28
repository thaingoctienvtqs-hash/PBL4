# Vận hành tích hợp phần mềm ArtGuard TEST

Tài liệu này là hướng dẫn vận hành; kết quả chạy thực tế được ghi trong báo cáo RESULTS của phiên. Có địa chỉ trong hướng dẫn không đồng nghĩa dịch vụ đang chạy. Không cần ESP32-CAM để xem dữ liệu SYNTHETIC_TEST.

## Phạm vi và các đường dẫn

- Repository: `C:\Users\LEGION\Pbl4`, branch `test-web`.
- Python backend có sẵn: `web\backend\.venv\Scripts\python.exe`.
- RUN hiện tại: `C:\Users\LEGION\ArtGuard-FullIntegration-Test\resume_20261028T093118720743Z_46cdffd7`.
- SQL TEST: `DESKTOP-2K5T32D\SQLEXPRESS`, loopback đã cấu hình `127.0.0.1:56929`, database `ArtGuard_Integration_TEST`.
- Không ghi vào `pbl4_art_guard`. Không chạy migration/seed mặc định của backend sản phẩm.
- Windows login vẫn có quyền sysadmin. Session app impersonate `artguard_integration_app`; đây không phải credential quyền thấp độc lập.
- Worker v3 và thuật toán AI không được sửa. Các nguồn DEMO, SYNTHETIC_TEST và REAL_AI phải giữ đúng provenance.

## Mở website TEST

PowerShell, dùng đúng repository:

```powershell
Set-Location C:\Users\LEGION\Pbl4
$Run = 'C:\Users\LEGION\ArtGuard-FullIntegration-Test\resume_20261028T093118720743Z_46cdffd7'
$Python = Join-Path (Get-Location) 'web\backend\.venv\Scripts\python.exe'
& $Python -B -m debug.full_integration.launch_test --run-root $Run start-backend
& $Python -B -m debug.full_integration.launch_test --run-root $Run start-frontend
& $Python -B -m debug.full_integration.launch_test --run-root $Run status
```

Launcher chỉ chấp nhận TEST profile; backend cần report bootstrap thành công cho đúng database. Cổng đã bị chiếm sẽ bị từ chối; không tự tắt process khác. Log mới và PID/creation-time được lưu trong RUN. Không chạy launcher sản phẩm `start_pbl4.bat` thay cho các lệnh này.

Sau khi status và HTTP được xác minh:
- Website: `http://127.0.0.1:5175`.
- Backend health: `http://127.0.0.1:8101/health`.
- Đăng nhập tên `integration_admin`, `integration_operator` hoặc `integration_viewer`. Giao diện ban đầu có thể điền `admin`; thay bằng tài khoản TEST.
- Mật khẩu TEST nằm trong `RUN\private_test_credentials.json`, mục `users`. Xem cục bộ bằng trình soạn thảo; không in ra terminal/log/chat, không đưa vào Git hoặc frontend. Producer tokens trong cùng file không phải mật khẩu người dùng.
- Dashboard ở `/`, danh sách cảnh báo ở `/alerts`. Tự cập nhật khoảng 2 giây sau khi request trước hoàn tất. Mở “Xử lý” để xem event ID, producer, source event và evidence.
- SYNTHETIC_TEST là fixture phần mềm, không phải camera hoặc inference thật. UNVERIFIED nghĩa là chưa có receipt xác minh nguồn, không tự coi là REAL_AI.

## Tạo một sự kiện mô phỏng qua outbox thật

Các lệnh sau tạo thư mục case mới và JPEG có chữ SYNTHETIC_TEST. Nguồn SQLite synthetic được ghi rõ trong `RUN\synthetic_source.json`: mỗi prepare append một event mới có source ID tăng dần, không sửa row cũ. Outbox mỗi case tách riêng; reader/sender không ghi vào nguồn. Không áp dụng prepare lên EventStore của worker thật.

```powershell
$Prepared = & $Python -B -m debug.full_integration.software_e2e prepare --run-root $Run | ConvertFrom-Json
$Case = $Prepared.case
& $Python -B -m debug.full_integration.software_e2e deliver --case $Case
& $Python -B -m debug.full_integration.software_e2e verify --case $Case
```


RUN hiện tại đã có `synthetic_source.json`, nên prepare không cần chọn lại nguồn. Nếu khôi phục một RUN cũ có case nhưng chưa có manifest, lần đầu phải chọn rõ case cũ để giữ producer namespace:

```powershell
$SourceCase = Join-Path $Run 'synthetic_20261028T093906752598Z_fb013c7f'
$Prepared = & $Python -B -m debug.full_integration.software_e2e prepare --run-root $Run --source-case $SourceCase | ConvertFrom-Json
$Case = $Prepared.case
```

Không xóa source DB/manifest hoặc khởi tạo lại ID từ 1 với cùng producer_instance_id. Nguồn thiếu hoặc khác namespace phải dừng, không tự tạo DB mới dưới danh tính cũ.

Giữ nguyên `$Case` cho replay/recovery. Không sửa payload/event ID của case đã gửi. Sender lưu ACK riêng; event đã DELIVERED không được gửi vô hạn. `verify` chủ động kiểm tra replay, conflict, auth, provenance và SQL persisted receipt. Từng lần verify thêm artifact mới; không xóa dữ liệu TEST.

Khi backend chưa chạy, outbox giữ retry/backoff. Khởi động backend rồi gọi deliver sau thời điểm retry được phép. RETRY_EXHAUSTED cần thao tác requeue rõ ràng bằng CLI sender `--retry-exhausted`; không đổi trạng thái DELIVERED hoặc xóa outbox để chạy lại. Khóa producer đọc từ môi trường của process, không truyền token trên command line.

## Kiểm tra an toàn và tắt dịch vụ

```powershell
& $Python -B -m debug.full_integration.sql_test_admin --run-root $Run --action inspect
& $Python -B -m unittest debug.full_integration.test_launch_test -v
& $Python -B -m debug.full_integration.launch_test --run-root $Run stop-test
```

`inspect` chỉ đọc danh tính SQL và ghi report mới trong RUN. Không tự bootstrap lại nếu schema chưa được kiểm tra. `stop-test` chỉ dừng PID có identity khớp registry của RUN; không dừng SQL Server, không xóa bảng, SQLite, evidence hay artifacts. Identity mismatch phải kiểm tra thủ công; không tự kill process theo tên.

Không chạy toàn bộ pytest hoặc `npm run build` trong quy trình này. Dùng TypeScript noEmit và Vite build với cache/output external; build hiện có nằm trong `RUN\frontend_dist_verified`. Không dùng `--emptyOutDir` trên artifacts cũ.

## Diễn giải latency và chất lượng

Các duration trong report dùng monotonic clock của từng process. EventStore → outbox, HTTP/ACK và truy vấn SQL chỉ là latency phần mềm. Polling 2 giây cộng thời gian request, không bảo đảm mục tiêu 300/500 ms. DOM_RENDERED_VISIBLE_TAB sau hai animation frame không chứng minh người thật đã nhìn thấy cảnh báo. Không trừ các clock khác nhau khi chưa đồng bộ.

Không dùng test logic hoặc SYNTHETIC_TEST để tuyên bố Accuracy >80%, Precision/Recall/F1 đạt 80%, hoặc đo độ trễ chạm tranh → ALERT. Inference offline, nếu chạy, cũng phải báo riêng khỏi hardware E2E.

## Checklist buổi nhóm có phần cứng — chưa thực hiện

1. Xác nhận nguồn, nhiệt độ, reset/FB-OVF và Wi-Fi; xác minh IP hiện tại, không dùng IP cũ tự động.
2. OV3660 gắn trực tiếp sát mép trên khung tranh, nhìn xiên xuống dọc bề mặt. Góc nghiêng/FOV/vùng mù chưa đo thì ghi UNKNOWN.
3. Dừng toàn bộ stream/capture trên Chrome và script khác; chỉ một consumer ESP32-CAM. Xin phép chụp đúng một frame.
4. Kiểm tra ánh sáng, nét, hướng, độ phủ, bàn tay ở mép ảnh. Raw frame không overlay được giữ riêng.
5. Chọn ROI polygon theo bốn góc phần tranh cần bảo vệ; người dùng xác nhận frame hiện tại. Không tự lấy toàn ảnh hoặc tái dùng ROI cũ.
6. Tạo session TEST mới, config tồn tại, tất cả output/SQLite/evidence riêng; model local, không tải hoặc thay weights. Không sửa v3/ngưỡng/temporal.
7. Chạy receiver Windows và worker file-watch WSL đã kiểm tra CLI, giới hạn thời gian; không mở consumer camera thứ hai. Worker chỉ chạy sau phê duyệt hardware.
8. Kiểm tra event thật đã commit trong EventStore; sender đọc read-only và có session provenance REAL_AI hợp lệ. Không đổi nhãn dữ liệu cũ thành REAL_AI.
9. Xác minh cùng event ID qua receipt SQL TEST, API, Dashboard và ảnh evidence có auth.
10. Thử bề mặt mô phỏng: không tay, tay in sẵn, tay ngoài ROI, tay gần nhưng không chạm, tay chạm rồi giữ yên, mất detection và camera offline. Không chạm tác phẩm thật.
11. Camera phụ bên hông chỉ xác minh ground truth; ghi đồng bộ/sai số. UNKNOWN không biến thành NO_TOUCH.
12. Đo từng stage, cold/warm, đồng bộ CUDA khi đo GPU, capture timestamp UNKNOWN nếu nguồn không cung cấp. Không dùng mtime làm capture time.
13. Thu nhiều phiên/người/ánh sáng; chia validation/test theo phiên, khóa tham số trước test độc lập. Ghi false positive, missed event và UNKNOWN.
14. Dừng đúng process sở hữu, giữ dữ liệu và log; ghi blocker. Chỉ tuyên bố HARDWARE E2E PASS sau phép thử thật có bằng chứng.
