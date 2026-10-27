# Kiểm kê dữ liệu read-only

Ngày: 2026-10-18. Gốc: `C:\Users\LEGION\Pbl4`; external: `C:\Users\LEGION\Datasets\ContactHands`.

## 1. Phạm vi và kết quả thực tế

Quét PBL4, không theo symlink, loại .git/node_modules/.venv/venv/__pycache__/dist/build. Tìm video theo .mp4/.avi/.mov/.mkv/.webm/.m4v/.mts/.wmv. Không tìm trên toàn bộ máy hoặc các thư mục cá nhân khác; 0 video chỉ áp dụng phạm vi này và dataset external đã nêu. Không mở SQLite/SQL Server.

| Dữ liệu | Kết quả | Giá trị cho recovery |
|---|---|---|
| Ảnh PBL4 | 72 file, 72 SHA-256 khác nhau; Pillow verify và decode đủ 72, không lỗi | Có thể xem xét chất lượng ảnh/crop bằng tay; chưa có danh tính |
| src/data/alerts | 63 JPG, nằm trong 72 ảnh | Evidence có overlay; track ID là output AI, không phải GT |
| Ảnh khác | src/data/latest.jpg, data/camera_frame.jpg, 2 ảnh camera ở root, 1 webcam JPG tên đường dẫn bị mã hóa, 3 PNG synthetic, 1 ảnh uploads backend | Không phải chuỗi video có nhãn; ảnh upload có thể là ảnh tác phẩm |
| Kích thước | 320×240: 5; 800×600: 4; 1200×896: 3; 640×480: 59; 367×500: 1 | Ảnh nhỏ/mờ là rủi ro appearance |
| EXIF thời gian | Không có DateTime/DateTimeOriginal trong cả 72 ảnh | Không thay thế bằng mtime hoặc suy đoán từ tên file |
| Video hiện diện | 0 trong phạm vi quét | Chưa thể đánh giá liên tục sau occlusion |
| src/data/history.json | 66 record; 17 image reference không rỗng, 0/17 tồn tại trong src/data/alerts | Lịch sử không đủ để dựng lại các frame/cặp hand_id |

72 hash khác nhau chỉ có nghĩa không trùng byte. Chưa kiểm tra near-duplicate; không suy ra 72 mẫu độc lập.

Đã nhìn trực tiếp `camera_hand_test.jpg` và `src/data/alerts/suspected_contact_track_22_20261016_080200_088385.jpg`. Có tay/ảnh tranh và evidence có chữ, bbox, ROI. Không thể khẳng định cùng người/cùng bàn tay hoặc tiếp xúc vật lý chỉ từ hai ảnh. Chữ “T22 ALERT” không tạo ra ground truth. Overlay có thể làm đặc trưng học/so khớp theo track ID, màu box, ROI hoặc background thay vì bàn tay. Cần raw frame trước overlay; không inpaint để biến evidence thành raw.

## 2. Metadata khác với file đang có

- `dataset/custom/metadata/annotation_manifest.json`: tasks=[].
- `dataset/custom/splits/source_groups.json`: train/val/test và source_groups rỗng.
- `dataset/custom/reports/custom_readiness.json`: báo cáo cũ có 0 phiên custom/0 frame/0 task/0 contact event. Thống kê public pilot cũ không chứng minh ảnh còn hiện diện.
- `dataset/metadata/acquisition_manifest.json`: 163 entry (validated 135, recovered 26, superseded_duplicate 2), là lịch sử thu nhận.
- `dataset/metadata/provenance.jsonl`: 426 record, 0/426 đường dẫn primary tồn tại. Gồm 100 ảnh Open Images, 158 masks, 158 converted annotations, 10 ảnh Met. **Không phải 426 ảnh**.
- `dataset/public/` hiện không có ở vị trí đã ghi. Không kết luận dữ liệu bị xóa vĩnh viễn; có thể ở ngoài phạm vi khảo sát.
- `dataset/synthetic/art_contact/metadata/synthetic_manifest.jsonl`: 60 record SYNTHETIC, 0/60 image_path tồn tại. Ba PNG synthetic trong data/ có tồn tại nhưng không phải bằng chứng identity thực.
- `dataset/README.md` không phản ánh đầy đủ metadata hiện có; giữ nguyên tài liệu cũ.

Không dùng acquisition status, source_image_id, source_box_id hoặc tên ảnh làm hand_id.

## 3. ContactHands external: đọc đủ XML

| Nội dung | Đã kiểm tra |
|---|---|
| JPEGImages | 20.506 file .jpg; không tìm thấy video trong external root |
| Annotations | 20.506 XML, parse đủ, 0 lỗi cú pháp XML |
| Object | 58.033 object |
| Split | train 18.877 ID duy nhất; test 1.629 ID duy nhất |
| Nhãn có | bbox, 4 điểm polygon, contact_state, pose/truncated/difficult |
| Không có trong tag/attribute toàn bộ XML | hand_id/person_id/track_id/identity_id/session_id/frame_id/video_id/timestamp/occluded/occlusion |

Không có XML attribute. Union tag gồm annotation/folder/filename/source/database/size/width/height/depth/segmented/object/name/pose/truncated/difficult/bndbox/xmin/xmax/ymin/ymax/x1..x4/y1..y4/contact_state. Nhãn truncated/difficult không mô tả danh tính hay episode che khuất.

Loader `src/datasets/load_data.py:42` dùng filename làm image_id; dòng 56–60 đọc contact_state/bbox. Không tạo hand identity. Tên kiểu test_4653_3 không được tài liệu/annotation đã kiểm tra chứng minh là chuỗi thời gian hoặc cùng người.

Lần này không decode lại toàn bộ 20.506 JPEG, không chạy validator tọa độ hoặc tái đánh giá ContactHands. 0 lỗi XML parse không đồng nghĩa annotation đã được xác nhận sạch về ngữ nghĩa.

## 4. Độ đầy đủ nhãn cần thiết

| Trường | Tình trạng |
|---|---|
| hand_id vật lý, phân biệt hai tay cùng người | Thiếu |
| session/capture_group thật và liên kết nhiều frame | Thiếu bộ có thể xác minh; metadata custom rỗng |
| bbox | ContactHands có; evidence vẽ box không thay thế annotation có cấu trúc |
| capture timestamp/PTS từng frame | Chưa có chuỗi liên tục đáng tin; tên file/history walltime không đủ |
| occlusion/gap/replacement và continuity review | Thiếu |
| contact ground truth độc lập | Chưa có bộ video được xác nhận |
| raw ảnh không overlay | Có một số ảnh rời, chưa đủ làm identity benchmark |

`inference/dataset_collector.py:26–45` lưu thư mục phiên và metadata FPS/date một lần; dòng 49–55 lưu frame theo index, không lưu timestamp capture từng frame. `inference/camera_base.py:33–40` chưa có trường capture timestamp tường minh trong CameraFrame. Chỉ đọc source, không khởi chạy collector. Cần bổ sung ở một lượt được phê duyệt riêng; không suy timestamp từ FPS danh nghĩa khi mất frame.

## 5. Bằng chứng Phase F và giới hạn kết luận

`phase_f/README.vi.md:7–9`: strict mặc định từ chối identity recovery khi thiếu bằng chứng; geometry opt-in có nguy cơ false positive.
`phase_f/recovery_tracker.py:14–23`: cửa sổ recovery bị chặn bởi timeout.
`phase_f/identity_observability.json`: phản ví dụ đầu vào hình học giống nhau nhưng identity truth khác nhau. Đây là bằng chứng logic, không phải thử appearance.
Không sửa hoặc chạy lại quality gate FAIL cũ. Không thể kết luận histogram/embedding sẽ phân biệt được phản ví dụ khi chưa có ảnh.

## 6. Kết luận audit

**Chưa đủ dữ liệu** cho định lượng Re-ID/recovery. Các bước tiếp theo chỉ là collection protocol, schema và thiết kế so sánh. Inventory chi tiết và hash nằm trong data_inventory.json. Các file không hiện diện được báo riêng, không tạo thay thế giả.
