# ContactHands Phase D — thử nghiệm logic độc lập

Chỉ bổ sung trong thư mục này. Không thay v3/v4, source sản phẩm, dữ liệu, checkpoint, DB hoặc môi trường. Không có camera worker hay GPU adapter trong Phase D.

## Chạy lại an toàn trên Ubuntu WSL

```bash
cd /mnt/c/Users/LEGION/Pbl4
/home/legion/miniconda3/envs/contacthands/bin/python -B -m debug.alert_diagnostics.v4.phase_d.run_tests
```

Runner kiểm tra hash trước khi chạy; ghi độc quyền vào thư mục mới `runs/logic_<UTC>_<uuid>/`. Không gọi runner cũ vốn ghi artifacts B/C.

Exit 0 nghĩa là D PASS, hash khớp và bộ B/C tái hiện đúng 98 PASS + 5 FAIL đã biết. **Không có nghĩa toàn bộ test B/C PASS.** Các FAIL cũ vẫn được lưu nguyên traceback; không dùng expectedFailure, skip hoặc sửa test B/C. Exit 1 nếu xuất hiện khác biệt ngoài tập FAIL đã biết, test D lỗi hoặc hash không khớp.

## Thiết kế và hợp đồng

### Thời gian và FPS

`temporal_d.py` giữ deque 5 phiếu riêng; hàng đợi thời gian giữ mẫu chưa quá 6 giây, tối đa 2048 mẫu. Vẫn cần score hiện tại hợp lệ và:
- nhánh thường: tối thiểu 3/5 phiếu, hỗ trợ >=0.4 giây;
- nhánh nhanh: tối thiểu 2 mẫu liên tiếp score >=0.85, span >=0.2 giây.

Một khoảng hỗ trợ chỉ nối hai quan sát liên tiếp đều hợp lệ, cách nhau <=2 giây, đóng góp tối đa 0.5 giây. Đây là hỗ trợ suy ra từ quan sát rời rạc, không chứng minh liên tục vật lý giữa hai ảnh. Mất detection xóa bằng chứng; gap >2 giây xóa bằng chứng dù ID còn sống. Timestamp trùng/cũ/NaN và frame trùng không được cộng. Mẫu hết hạn bị loại trước xác nhận. EMA chỉ là telemetry.

Ngưỡng hand=0.7, Object-Contact=0.15, fast=0.85, overlap=0.3 giữ nguyên. Thời gian giữ ID mặc định 2 giây độc lập với thời gian bằng chứng. Timeout 1/2/3 chỉ là các ứng viên, chưa tối ưu trên dữ liệu thật.

Thời gian lưu bằng chứng dài hơn v4 cũ có thể tăng xác nhận trên các đợt score ngắt quãng trong 6 giây. Đây là đánh đổi cần đánh giá false positive trên video độc lập, không phải bảo đảm AI chính xác hơn.

Ở 1 FPS, 2 giây tiếp xúc cho 2 mẫu trong ROI không đủ 3 phiếu. Test giữ giới hạn này; test tiếp xúc kéo dài dùng 3 giây cho mọi FPS. Không bỏ bảo vệ số phiếu để ép thời gian trễ giống nhau.

### Disconnect và reconnect

`PipelineD.disconnect()` là đường điều khiển riêng, không qua cache/dedup/staleness/timestamp gate dữ liệu. Control hợp lệ của session hiện tại luôn xóa ID/entry/history/ALERT active, trả CAMERA_OFFLINE và decision_available=false, kể cả timestamp control lỗi. Control của session cũ bị từ chối.

Sau disconnect, dữ liệu bị từ chối cho tới `reconnect(new_session, calibration_id)`. Session phải mới, cache dữ liệu reset, ID không tái dùng. Camera phải có bằng chứng nền mới khớp mốc hiệu chuẩn và tay phải đi vào ROI lại. Tay có sẵn bên trong không tự được xác nhận.

**Không có watchdog nền:** adapter tương lai phải gọi disconnect khi capture timeout/mất camera, dùng cùng session hiện tại. Khi không có lời gọi nào, module thuần logic không tự phát hiện mất kết nối. Caller phải tôn trọng decision_available=false, không tái sử dụng ALERT cũ từ UI cache.

Frame cache vẫn có giới hạn 4096 của v4; khi đầy, data path dừng và cần rollover session rõ ràng, không âm thầm quên ID frame. Control disconnect vẫn hoạt động khi đầy.

### Danh tính tracking

`tracking_d.py` ưu tiên khoảng cách tới vị trí dự đoán; dùng tối ưu ghép toàn cục. Gần nhau <0.08 tọa độ chuẩn hóa, quỹ đạo dự đoán giao gần nhau, hoặc chi phí ghép gần bằng nhau => uncertain. Toàn thành phần ghép mơ hồ bị loại trước khi ghép; ID cũ bị retire, entry/history bị xóa. Detection mơ hồ chưa được tạo ID mới.

Đây là ngưỡng thử nghiệm hình học, chưa hiệu chỉnh ảnh thật. Đánh giá kiểm tra actor sở hữu ID bằng nhãn oracle chỉ trong test; matcher không dùng oracle. Không khẳng định duy trì được ID qua mọi che khuất/giao nhau hoặc chuyển động bất ngờ giữa các frame. Mất ID/entry làm giảm Recall, nhất là hai tay gần nhau nhưng thực ra độc lập.

### Camera stability: chưa có bằng chứng hình ảnh thật

Mặc định thiếu nguồn nền => CAMERA_UNVERIFIED, không tạo entry/contact/ALERT. Chuyển động nền => CAMERA_MOVING và xóa trạng thái tích lũy. Unknown cũng xóa active để không thể hiện camera đang giám sát hợp lệ.

`camera_stability.py` mới kiểm tra hợp đồng correspondence, **chưa trích xuất hoặc xác minh feature từ ảnh thật**:
- frame_id, timestamp, source_session, calibration reference phải khớp;
- >=20 điểm nền trên >=3 góc phần tư, sai số forward/backward <=0.002;
- inlier >=80%, reference displacement p95 <=0.005 mới coi là STABLE;
- so với reference hiệu chuẩn cố định, không reset mốc theo từng frame, tránh bỏ sót pan chậm.

Các số trên chỉ là tham số thử nghiệm chuẩn hóa, không phải metric AI hay ngưỡng đã chứng minh an toàn. Bộ lọc điểm vùng giữa ảnh chỉ là placeholder bảo thủ; adapter ảnh thật phải loại foreground/ROI/hand và xác minh vùng nền thực sự.

Provider `controlled_fixture` chỉ dùng khi test_mode=true. Provider ảnh ngoài chỉ mở qua allow_external_background=true có chủ đích; hiện mặc định tắt. **Không được bật để bypass kiểm tra khi chưa thẩm định extractor.**

Test cố tình cấp tín hiệu nền đứng yên sai cho ca pan vẫn sinh 1 ALERT. Nó chứng minh phụ thuộc vào độ tin cậy provider; bộ kiểm tra hợp đồng không xác thực nội dung ảnh. Không coi vài bbox/điểm giả lập là đã giải quyết camera pan.

Phương án ảnh thật cần đánh giá tiếp (chưa triển khai/chưa chạy): feature tracking trên mask nền cố định, forward/backward optical flow, robust affine/homography và so khớp mốc hiệu chuẩn; có phủ nhiều vùng, kiểm tra inlier/reprojection và photometric consistency. Texture kém, parallax, rolling shutter, rung/mờ => UNKNOWN. Phải thử video pan/rung trên tay in sẵn, tay thật và tranh không tay.

## So sánh có thể tái lập

`compare.py` giữ prediction đầu vào giống nhau cho v3, v4 và D; lưu hash prediction. Có hai cột D:
- controlled: thêm correspondence nền giả lập được gắn nhãn rõ; ca pan/jolt nhận tín hiệu nền chuyển động;
- unknown: thiếu chứng cứ ảnh như mặc định thực tế, tất cả quyết định unavailable.

Đây không phải so sánh chỉ khác thuật toán: D controlled nhận thêm giả định stability. Artifacts lưu đầy đủ prediction/context/output để kiểm tra giả định. Không diễn giải việc D unknown không ALERT là tăng Precision.

`test_phase_d.py` gồm quality gates, regression contracts và characterization giới hạn. Test PASS cho phản ví dụ provider sai hoặc hai đợt tiếp xúc cùng ROI **không có nghĩa chức năng đó đã được sửa**.

## File mới và artifacts

- Source: __init__.py, camera_stability.py, temporal_d.py, tracking_d.py, pipeline_d.py, fixtures.py, compare.py, run_tests.py, test_phase_d.py.
- Tài liệu: README.vi.md, RESULTS.vi.md.
- Hash trước: protected_before.json (90 file), protected_extended_before.json (281 file).
- build_inputs_01/02/03 và preflight_01/02/03.json: ứng viên và bằng chứng thử trước xuất bản; giữ nguyên cả lần lỗi.
- runs/: frozen_tests.json, phase_d_tests.json, comparison.json, replays.json, protected_after.json, summary.json.
- final_verification.json: kiểm tra hash/Git/static cuối lượt.

## Phạm vi đánh giá còn thiếu

Chưa tích hợp v3, camera, GPU, website/SQL Server. Chưa benchmark latency CPU/GPU; vòng quét time evidence và ghép nhiều ID cần đo khi tích hợp.

Accuracy, Precision, Recall, F1, confusion matrix, false alarms/hour, độ trễ cảnh báo thật: **CHƯA ĐÁNH GIÁ**. Tiếp tục dùng quy trình video độc lập và evaluator của Phase C; tách validation/test theo phiên quay, không chỉnh threshold trên test. Cần ghi cả thời gian unavailable/uncertain để tránh báo metric tốt do bỏ quyết định. Mục tiêu Accuracy >80%, Precision/Recall/F1 >=80% chưa được chứng minh.

Chỉ chạy kiểm thử logic trong giai đoạn này. Không chuyển sang camera/GPU nếu chưa có phê duyệt riêng.
