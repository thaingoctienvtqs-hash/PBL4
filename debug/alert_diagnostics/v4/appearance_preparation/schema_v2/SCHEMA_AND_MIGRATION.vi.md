# Schema v2, khác biệt v1 và quy tắc chuyển đổi đề xuất

## 1. Hợp đồng dữ liệu

schema_version=2.0. data_kind=REAL_CAPTURE hoặc SYNTHETIC_TEST. Mọi bundle fixture đều là SYNTHETIC_TEST, chỉ kiểm tra schema. Session/video/frame ID không lấy từ track ID AI hoặc suy đoán tên file.

Các mảng cơ bản: sessions, videos, reference_videos, synchronizations, calibrations, frames, hands, tracking_gaps, contact_events. Cần ít nhất một session/video/calibration/frame; bản ghi calibration UNMEASURED hợp lệ. **hands/tracking_gaps/contact_events có thể rỗng**. reidentification là block tùy chọn, gồm identity_links/pairs; không có nhu cầu Re-ID thì bỏ hẳn block.

| Nội dung | v1 | v2 |
|---|---|---|
| Camera | camera_id | sensor OV3660, TOP_EDGE_DIRECT, OBLIQUE_DOWNWARD, tilt/FOV/resolution có thể chưa đo |
| Video | media path ở session | video_id/segment_id riêng, path/hash/capture clock |
| Đồng bộ | clock chung, capture/receive | capture clock và host clock riêng; side reference/sync có offset, anchor, uncertainty, drift |
| ROI | đỉnh trong coordinates | giữ đỉnh normalized, thêm image_space và calibration/coverage |
| Độ phủ | chưa tường minh | FULL/PARTIAL/UNKNOWN; vùng ngoài FOV/occlusion/low-resolution |
| Tay | hand_id/bbox/depicted | giữ ý nghĩa, thêm video và vị trí lần đầu quan sát |
| Tiếp xúc | contact/no_contact/uncertain | TOUCH/NEAR_NO_TOUCH/NO_TOUCH/UNKNOWN, scope, biên event, nguồn xác minh |
| Cảnh không tay | hands/gaps/pairs minItems=1 | hợp lệ, không bịa tay/gap/pair |
| Re-ID | pair/gap bắt buộc | riêng, tùy chọn; không truyền entry/history |

## 2. Camera, clock, độ phủ

- Tilt đo từ mặt phẳng tranh: 0 độ song song, 90 độ theo pháp tuyến. Chưa đo thì tilt_degrees và uncertainty đều null. Không gọi giá trị demo là phép đo.
- Configured resolution của camera khác kích thước ảnh thực. Chưa biết cấu hình camera: cả width/height null. Kích thước raw frame OK phải biết và khớp video resolution khi video đã biết.
- capture_timestamp_ms dùng clock/PTS nguồn, host_receive_timestamp_ms dùng clock host. Không so sánh hai epoch trực tiếp, không dùng thời gian nhận làm thời gian capture.
- timestamp UNKNOWN phải để capture null. DUPLICATE/STALE là annotation lỗi đầu vào, không phải contact evidence.
- Sync mapping ghi offset tại primary_anchor_ms: reference_ms = primary_ms + offset_ms tại anchor. Drift là metadata đo riêng, chưa có hàm tự áp dụng. uncertainty phải phản ánh sai số trên cả segment được dùng; kiểm tra tín hiệu đầu/cuối, nếu drift chưa khống chế thì chia segment hoặc hạ sự chắc chắn.
- Camera OFFLINE không có raw frame. MISSING/CORRUPT không phải NO_HAND và không được có hand observation.
- FULL nghĩa phần mặt tranh nằm trong FOV được xác nhận đầy đủ; visible fraction=1 là hệ quả nhãn FULL, không phải default. PARTIAL có vùng không quan sát được; tỷ lệ diện tích chưa đo vẫn null. Observable fraction không được vượt visible fraction.
- OUTSIDE_FOV không mô tả bằng tọa độ ảnh 0..1. Dùng ARTWORK_NORMALIZED nếu có căn cứ; nếu chưa biết extent thì UNKNOWN + coordinates=null. Không kéo góc tranh ra ngoài ảnh bằng suy đoán.
- Vùng tay che tạm thời ghi occlusion/visibility của observation, không liên tục thay ROI nền.

## 3. Identity, contact và review

hand_id định danh một bàn tay vật lý trong session; hai tay cùng người có ID khác. Unknown identity => null, không dùng model track ID. DEPICTED_HAND có depiction_id, không có physical hand_id. Annotation identity VERIFIED không tự cho phép ROI entry hoặc TOUCH.

TOUCH và NEAR_NO_TOUCH cần observation tay thật. NEAR_NO_TOUCH cần near_definition ghi tiêu chí đã thống nhất và nguồn chứng minh khoảng hở. Bbox không phải phép đo khoảng cách tới tranh.

Ground truth gồm VERIFIED/UNVERIFIABLE, nguồn PRIMARY_VIDEO/SIDE_REFERENCE/INDEPENDENT_OBSERVER/UNRESOLVED, evidence_notes và review. Nhãn đã biết cần APPROVED với ít nhất hai reviewer ID khác nhau. UNKNOWN phải UNVERIFIABLE; không tự đổi thành NO_TOUCH. Validator chỉ kiểm tra hợp đồng, không xác thực người đã thật sự xem video.

SIDE_REFERENCE liên kết reference_id/sync_id; nhãn known trên timeline chính cần sync MEASURED. Camera phụ chỉ phục vụ GT, không đưa vào matcher hoặc ContactHands.

Event dùng interval [start_timestamp_ms, end_timestamp_ms), theo capture clock video chính; biên không biết để null, không điền 0. start/end_frame_id có thể null. scope=HAND cần observation refs; scope=SCENE dùng cho khoảng tổng thể như không có tay. Hai tay khác nhau có thể có nhãn đồng thời khác nhau. TOUCH và NO_TOUCH cùng scope/thời gian là mâu thuẫn. Không chấm event latency khi thiếu biên/sync đủ tin cậy.

## 4. ROI annotation và runtime: tuyệt đối không chép trực tiếp

Cả v1/v2 annotation dùng coordinates = [[u0,v0], ...], đỉnh normalized theo ảnh. Rectangle phải có bốn góc trục song song, đúng thứ tự quanh biên. Tứ giác phối cảnh dùng polygon. ROI hiện tại chỉ kiểm tra polygon lồi, không tự cắt/chuẩn hóa dữ liệu.

Runtime src/utils/config_compat.py khác:
- rectangle: coordinates=[xmin,ymin,xmax,ymax], bốn số;
- polygon: points=[[u0,v0], ...], normalized=true; config_compat tính thêm envelope coordinates.

Adapter tương lai phải kiểm tra source/video/resolution/image_space/calibration, polygon hợp lệ, rồi đổi tên trường cho polygon; rectangle chỉ flatten sau xác minh hình học. Không dùng envelope thay polygon xiên. ROI UNMEASURED/null hoặc chưa xác nhận coverage không tự bật enabled=true. UNDISTORTED cần kiểm tra hợp đồng biến đổi ảnh; schema v2 chưa cung cấp transform pipeline hoặc lịch sử map bbox về raw.

Không có adapter runtime được tạo/chạy trong lượt này.

## 5. Migration v1 -> v2: thiết kế, chưa thực thi

Không sửa annotation hiện có. Converter tương lai phải chạy dry-run, ghi output riêng độc quyền và ledger provenance gồm đường dẫn/hash nguồn, field cũ, field không map, người review; giữ bản v1 nguyên vẹn.

- Session/capture_group/hand/bbox/depiction giữ khi đã xác minh semantics; không đặt video_id bằng cách suy đoán filename. Video ID mới chỉ từ asset/source thật đã đối chiếu.
- clock_id cũ không chứng minh capture và receive cùng clock. Chưa xác minh: capture=null/status UNKNOWN; giữ giá trị cũ trong ledger, không tự chuyển epoch.
- Trường vị trí lắp/góc/FOV/coverage cũ thiếu phải được người review xác nhận. Không áp const TOP_EDGE_DIRECT cho ảnh public hoặc ảnh từ vị trí camera khác.
- contact chỉ map TOUCH sau review bằng chứng chạm thật. no_contact không tự chia NEAR_NO_TOUCH/NO_TOUCH. uncertain -> UNKNOWN. Khi chưa đủ xác minh: UNKNOWN và ghi legacy label trong ledger.
- ROI points chỉ giữ trong v2 khi đã đối chiếu đúng reference frame/calibration: dùng ANNOTATED và coverage UNKNOWN nếu chưa biết độ phủ. Chưa đối chiếu được ảnh: calibration UNMEASURED, roi=null; giữ ROI cũ trong ledger để review, không làm mất bản v1. Không suy góc/FOV từ polygon.
- Pair/gap cũ chỉ map sau review physical identity; chuyển pair/link vào block reidentification tùy chọn. Không lấy dữ liệu B–F tổng hợp làm nhãn ảnh thực.
- Số UNKNOWN có thể tăng sau migration; đó là phần chưa xác minh, không sửa nhãn để ép số liệu đẹp.

Chưa có converter và chưa migration bất kỳ file nào.

## 6. Những điều chưa biểu diễn/kiểm chứng đầy đủ

Schema không chứa mask tay/fingertip/depth/contact force; không chứng minh tiếp xúc vật lý. Chưa có polygon ROI lõm/multiple components/holes tương thích runtime. Chưa có mô hình distortion/extrinsics và provenance đầy đủ cho ảnh đã warp; chỉ có ID/metadata tùy chọn. Đồng bộ phi tuyến, rolling shutter và uncertainty theo từng pixel chưa được mô hình hóa; chia segment và ghi UNKNOWN khi thiếu căn cứ.

Semantic validator chặn exact-hash leakage trong cùng bundle; chưa chứng minh khoảng thời gian review phủ đủ mọi frame, không tự phát hiện near-duplicate/person leakage giữa các bundle riêng, không xác thực GT/reviewer, và không chứng nhận độ ổn định camera từ ảnh. REAL_CAPTURE marker cũng không tự xác thực file là dữ liệu thật.
