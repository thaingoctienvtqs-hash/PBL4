# Checklist camera sát mép trên tranh — chưa thực hiện

Không chạy camera hoặc thay config trong lượt chuẩn bị. Chỉ đánh dấu sau khi nhóm thực hiện và có bằng chứng. Trường chưa đo giữ null/UNKNOWN.

## Vị trí và ảnh nguồn

- [ ] ESP32-CAM OV3660 gắn trực tiếp sát mép trên khung tranh, TOP_EDGE_DIRECT.
- [ ] Nhìn chếch xuống dọc bề mặt tranh, OBLIQUE_DOWNWARD.
- [ ] Chụp ảnh vị trí lắp để làm provenance; không suy góc từ hình minh họa.
- [ ] Kiểm tra cố định cơ học; ghi khả năng rung khi tay chạm khung/tranh.
- [ ] Ghi source/camera/session/video/segment ID và resolution thật từ raw frame.
- [ ] Chỉ một consumer ESP32-CAM, lưu raw trước bbox/ROI/text overlay.

## Góc, lens và ROI

- [ ] Ghi quy ước đo tilt từ mặt phẳng tranh; đo và ghi uncertainty hoặc để null.
- [ ] FOV ngang/dọc chưa đo thì null; không dùng thông số lens suy đoán.
- [ ] Lấy reference frame không có tay che, giữ path/hash và calibration_id.
- [ ] Chọn bốn góc nếu thấy đủ; nếu không, chọn polygon phần mặt tranh thực sự thấy.
- [ ] Không tự chọn full image; không tưởng tượng góc ngoài khung.
- [ ] Điểm normalized 0..1, đúng thứ tự quanh biên, không trùng/tự cắt; polygon runtime hiện chỉ hỗ trợ lồi.
- [ ] Rectangle chỉ dùng cho bốn góc trục song song; mặt tranh xiên dùng polygon.
- [ ] Ghi RAW/UNDISTORTED; không trộn ROI từ ảnh sửa méo với bbox ảnh gốc.
- [ ] Nếu lens làm biên cong rõ, ghi giới hạn; chưa tự warp đầu vào ContactHands.
- [ ] Homography chỉ nghiên cứu khi có đủ điểm tương ứng không suy biến. Nó không đo khoảng hở tay–tranh.
- [ ] Chưa có adapter ROI v2 -> runtime được xác minh thì không nạp ROI annotation vào worker.

## Độ phủ và quan sát

- [ ] Đánh dấu FULL/PARTIAL/UNKNOWN bằng bằng chứng, không mặc định FULL.
- [ ] Đánh dấu OUTSIDE_FOV/STATIC_OCCLUSION/LOW_RESOLUTION; extent chưa biết để null.
- [ ] Xác định vùng gần/giữa/xa nào nhìn được tay đủ rõ; không coi ảnh có pixel là quan sát tin cậy.
- [ ] Không co ROI khi tay che; ghi occlusion/visibility riêng.
- [ ] Nếu tay được phát hiện lần đầu bên trong ROI, ghi đúng annotation; không tự bật ever_entered_roi.
- [ ] Reference tay in sẵn không chứa tay thật; tránh biến tay thật đang giữ yên thành nền.

## Clock, camera phụ và duyệt

- [ ] Capture clock/PTS và host receive clock được ghi riêng.
- [ ] Camera phụ bên hông nhìn được khoảng hở và bề mặt chạm.
- [ ] Có tín hiệu sync ở đầu/cuối, offset/anchor/uncertainty được đo; không mặc định offset=0.
- [ ] Drift/sai số thay đổi được ghi; chia segment hoặc UNKNOWN nếu không kiểm soát.
- [ ] Hai reviewer xác minh TOUCH/NEAR_NO_TOUCH/NO_TOUCH; thiếu căn cứ => UNKNOWN.
- [ ] Hash media, khóa capture_group và split theo phiên trước tune.
- [ ] Camera đổi góc/resolution/ROI hoặc reconnect cần phiên/calibration phù hợp; không dùng history cũ.
- [ ] Duyệt schema + ảnh hiệu chuẩn trước khi phê duyệt inference thực tế.

Hoàn thành checklist không đồng nghĩa AI đạt 80%.
