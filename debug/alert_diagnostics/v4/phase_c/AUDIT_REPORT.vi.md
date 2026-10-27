# Kiểm toán chất lượng v4 — kết quả thực tế

## Phạm vi và kết quả

Chỉ tạo/sửa mã mới dưới phase_c/. Không sửa module v4 Giai đoạn B hoặc source sản phẩm.
Python 3.7.16, không import torch/cv2/Detectron2, không mở camera/GPU/database.
Lượt cuối 103 test: 98 PASS, 5 FAIL, 0 ERROR; 75 so sánh trên cùng input.
Hash 45 file được bảo vệ khớp: 34 file/artifact v4 cũ và 11 file nguồn/checkpoint/working-change.
Xem protected_verification.json để biết đối chiếu cuối, file và phạm vi cụ thể.

## Rà soát 40 test cũ

baseline_test_review.json ghi đủ 40 tên test, dòng code và nhận xét; 4 test tạo kết quả v3
nhưng không assert kết quả đó. Không có bằng chứng cố ý thiên vị, nhưng có các lỗ hổng:

- test_v4_candidate_timeout_not_v3_default so v3 timeout 1 với v4 timeout 2:
  chứng minh lợi ích cấu hình, không chứng minh thuật toán v4 tốt hơn.
- Các case tích cực dùng nhịp 0.2s phù hợp duration guard; không phủ 15–30 FPS.
- test_multiple_hands dùng các tay cách xa: hai ID vẫn có thể giữ nguyên số lượng nhưng đổi chủ.
- test_ambiguous_crossing chỉ phủ tie chính xác, không phủ cost tự tin nhưng ghép sai.
- test_depicted_static kiểm tra gate hình học, không phải nhận diện tay thật/tay in.
- Ít ALERT hơn ở score dao động có thể là ít FP hoặc nhiều FN; chưa có nhãn để phân biệt.
- test_same_episode_resume giả định một entry episode là một lần chạm vật lý:
  có thể làm test PASS bằng cách bỏ sót lần chạm thứ hai trong cùng ROI.
- Test ROI mới chỉ tạo object mới; không phát hiện mutation trực tiếp config.
- Polygon cũ là rectangle biểu diễn bằng bốn điểm, chưa đủ phủ camera nhìn chếch.
- Assignment một ma trận cố định chưa đủ; đã thêm 60 ma trận seeded đối chiếu brute-force.
- Reject frame trước đây chưa snapshot toàn state; đã thêm kiểm tra entry/temporal/ID đầy đủ.

## Năm quality FAIL, bốn nguyên nhân gốc

### High — cửa sổ 5 mẫu làm duration guard không thể đạt ở FPS cao (2 FAIL)

temporal_v4.py:9 dùng deque maxlen=5.
temporal_v4.py:49–60 tính support và fast span trên chính deque này.
temporal_v4.py:83–85 yêu cầu fast span >=0.2s hoặc support >=0.4s.

Tối đa chỉ có 4 khoảng trong deque. Với nhịp đều f:
support <=4/f; fast span <=4/f.
Ở 30 FPS, cả hai <=0.1333s, thấp hơn cả hai điều kiện.
Phản ví dụ giữ nguyên entry/ID/score trong 2s:
- score 0.6: v3 1 event, v4 0.
- score 0.99: v3 1 event, v4 0.
Sweep: 10 FPS score .6 phát event; 15/20 FPS .6 không;
20 FPS .99 có, 25/30 FPS .99 không.
Đây là lỗi tính nhất quán theo nhịp quan sát, chưa phải recall đã đo trên camera.

Đề xuất ưu tiên: tách last-5 vote window khỏi queue hỗ trợ thời gian/fast streak.
Giữ ngưỡng OC/duration; không chữa bằng giảm ngưỡng hoặc cố tình hạ FPS.
Kiểm tra sampling invariance, timestamp và giới hạn bộ nhớ.

### High — camera pan bị hiểu là tay tiếp cận (1 FAIL)

roi_entry_v4.py:15–34 chỉ dùng bbox/ROI cố định, không biết chuyển động nền.
Chuỗi mô phỏng tay in sẵn dịch chậm .5 -> .3 -> .55 do camera:
v3 0 event, v4 1 event. Jolt nhanh: cả hai 1.
Đây là phản ví dụ nguy cơ FP có giả thuyết cảnh rõ ràng; không phải FP rate đo trên ảnh thật.

Đề xuất: camera pose/scene stability guard và hiệu chuẩn lại khi camera dịch chuyển.
Không suy ra camera motion chỉ từ bbox tay. Có thể dùng nền/ROI registration sau phê duyệt;
khi không đủ tin cậy, suspend entry/đánh dấu NEEDS_RECALIBRATION.

### High — chuyển ID giữa hai tay khi giao nhau (1 FAIL)

tracking_v4.py:94 cost dùng predicted center và IoU bbox cũ.
Trong crossing tốc độ hằng offset 0, v4 giữ đúng số lượng 2 ID nhưng có 2 lần ID đổi chủ.
Offset .01 gây fragmentation từ 2 thành 6 ID; offset .03 giữ ổn định.
Bộ tối ưu tổng cost được kiểm tra đúng trên 60 ma trận: vấn đề là cost/gating,
không phải bằng chứng solver Hungarian sai.

Đề xuất: đánh giá lại motion-vs-IoU cost, uncertainty theo dt, bảo vệ evidence khi crossing.
Appearance/ảnh có thể cần thiết ở occlusion; không cam kết giải quyết bằng bbox đơn thuần.

### High — cache đầy chặn disconnect (1 FAIL)

pipeline_v4.py:137–138 từ chối input khi cache đầy;
pipeline_v4.py:163–167 dùng cùng gate cho disconnect.
Cache 5 frame, đang ALERT, disconnect mới bị từ chối; track/active state còn giữ.

Đề xuất: tách control path khỏi data-frame capacity. Disconnect đúng source/session
phải clear trạng thái dù cache đầy. Vẫn kiểm tra identity/session của control event.

## Rủi ro Recall/FP khác, chưa coi là lỗi nhận diện đã đo

- Overlap ổn định .35 vượt contact threshold .30 nhưng chưa đạt entry-inside .40:
  v3 1 event, v4 0 (cùng timeout/ID).
- OC .151/.149 hoặc .6/.1 xen kẽ: v3 1, v4 0.
  Có thể là chống noise hoặc bỏ sót chạm thật; prediction giống nhau không phân biệt được.
- Missing xen kẽ liên tục: v3 1, v4 0; reset history bảo thủ có thể giảm recall.
- Hai đợt score cao, cách nhau hơn cooldown trong cùng ROI: v3 2, v4 1.
  physical-contact bouts phải do người gán nhãn, không đồng nhất với entry episode.
- Tay thật sinh sẵn trong ROI và tay in có cùng prediction: cả hai bị chặn.
- Mutation trực tiếp p.config ROI không reset evidence. Đây là cách dùng ngoài README contract,
  nhưng API thiếu guard; gọi mới PipelineV4 là cách an toàn hiện tại.
- Không có receive timestamp -> không xác định được tuổi frame; cần adapter clock thực.
- 4096 frame là giới hạn bounded replay, chưa phải luồng sản phẩm chạy dài.

## Cải thiện đã chứng minh và điều chưa chứng minh

- Đi chậm qua mép: v3 0, v4 1; entry tích lũy có tác dụng trên chuỗi kiểm soát.
- Reject timestamp/frame trùng không làm thay đổi state, missing không tăng evidence.
- Một đợt giữ yên sau entry vẫn chỉ một event.
- Cùng timeout 2/3s, cả hai giữ ID cho gap 1.01s; không gán lợi ích timeout cho v4.
- 75 so sánh dùng canonical input SHA256 chung; input được normalize chung.
- Baseline là pure v3 functions, không phải scheduler file-watch.
- Fewer events != better precision. Chưa có nhãn thật, chưa có model-quality metrics.

## Sẵn sàng và đề xuất thứ tự

1. Sửa time queue và disconnect control path trong một bản experimental mới sau phê duyệt.
2. Kiểm tra crossing/cost và camera stability; bổ sung các oracle đã lưu, không đổi chúng để xanh test.
3. Xác định contact-bout lifecycle, partial-ROI entry và miss policy trên validation có nhãn.
4. Thêm adapter prediction v4 và clock instrumentation, ROI hiệu chuẩn; camera test có giám sát riêng.
5. Khóa protocol/config, chạy test độc lập. Accuracy >80%, event P/R/F1 >=80% CHƯA ĐÁNH GIÁ.

Dừng sau Giai đoạn C. Không thay đổi source v4 để làm các quality gates PASS.
