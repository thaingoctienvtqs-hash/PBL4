# Thu thập và đánh giá độc lập — chưa thu video trong Giai đoạn C

## Mục tiêu và đơn vị

Primary: Accuracy trên cửa sổ nguồn 1 giây >80%;
Precision/Recall/F1 trên event tiếp xúc vật lý >=80%.
Báo cáo thêm P/R/F1 của classification, không tráo đơn vị để chọn số đẹp.
Chốt protocol.json và hash trước test; chỉ điều chỉnh trên pilot/validation.
Tất cả metric thực tế hiện CHƯA ĐÁNH GIÁ.

## Thu video thật sau phê duyệt riêng

Dùng một nguồn capture đang được duyệt, giữ firmware/môi trường.
Lưu bản gốc không annotate, source frame ID, timestamp/receive time và biến thiên inter-frame.
Không tăng tải ESP32 bằng hai nguồn stream. Không biến FPS encode thành thời điểm chụp giả.
Thử tiếp xúc trên tranh mô phỏng/bề mặt được phép chạm.

Mỗi phiên quay có video_id, session_id, capture_group_id, SHA256, camera/ROI/checkpoint hash,
người thực hiện, điều kiện ánh sáng/góc/độ phân giải/FPS đo được và phiên bản annotation.
Dự kiến ít nhất 6 phiên validation và 6 phiên test độc lập làm điểm bắt đầu;
đây không phải cỡ mẫu đủ đảm bảo thống kê hoặc mục tiêu 80%.

Các kịch bản bắt buộc:
- Chạm thật: đi nhanh/chậm từ ngoài, sát mép, xuất hiện sẵn trong ROI,
  chạm ngắn, giữ lâu, rút tay, chạm lại không rời ROI.
- Không chạm: đứng gần, đưa tay sát nhưng không chạm, đi ngang,
  giữ tay trước tranh, OC có thể cao nhưng người gán nhãn không xem score.
- Tay in sẵn: tĩnh, ánh sáng thay đổi, camera rung/pan, người thật đi qua hoặc che tranh.
- Không có tay: tranh/tường trống tay, nền chuyển động, mất camera/ảnh hỏng.
- Hai tay: giao nhau, che khuất, nhiều người, đổi thứ tự xuất hiện.
- Missing: gián đoạn ngắn/dài, nguồn dừng, reconnect; ghi riêng sự kiện kỹ thuật.

Thu đủ footage âm kéo dài để FA/hour có ý nghĩa, mục tiêu ban đầu >=1 giờ phân bố nhiều phiên.
Báo tổng giờ thật; không biến video lặp thành exposure độc lập.
Giữ cả case thất bại, không chỉ chọn clip dễ hoặc clip phát ALERT.

## Human labels

Người gán nhãn không xem prediction/score để quyết định physical touch.
Có thể dùng góc nhìn tham chiếu riêng hoặc đánh dấu quan sát trực tiếp đồng bộ.
Nếu không thể xác định chạm thật, ghi uncertain, không suy đoán từ 2D bbox.
Hai người gán nhãn, đối chiếu onset/offset, một bước adjudication; lưu bất đồng/version.
labels_approved=yes chỉ sau review.

annotation_intervals.csv phủ kín mỗi clip theo [start,end), không gap/overlap:
contact / no_contact / uncertain. Contact là bất kỳ tay nào thật sự chạm bề mặt mục tiêu.
contact_events.csv ghi mỗi physical-contact bout theo tay/tác phẩm;
hai tay có thể có interval event chồng nhau. Event không được phủ vùng uncertain/no_contact.
Hai lần chạm khác nhau trong ROI vẫn là hai bout, dù track ID không đổi.
Bảng này độc lập với ROI-entry episode và event_key của thuật toán.

## Split chống rò rỉ

Pilot chỉ phát triển quy trình. Validation để chọn policy/tham số; test khóa kín.
Chia theo toàn phiên quay/capture group, không cắt frame lân cận sang hai split.
Clip con của cùng raw recording luôn cùng group. Không tái dùng clip đã xem lỗi để test độc lập.
Hash trùng bị từ chối ngay cả cùng split; session/group khác split cũng bị từ chối.
Hash khác không chứng minh không phải clip con: review provenance thủ công là bắt buộc.
Nếu tuyên bố tổng quát sang người/tranh/camera khác, thêm holdout các nhóm đó và báo riêng.
Không bắt buộc tranh khác giữa split nếu mục tiêu chỉ deployment trên cùng tranh,
nhưng phải ghi rõ phạm vi suy rộng.

## Prediction, fairness và coverage

Tạo prediction một lần từ ContactHands nguyên checkpoint trên cùng frame; replay v3/v4 cùng input,
cùng ROI đã hiệu chuẩn, cùng source clock và sampling profile.
So riêng matched timeouts 1/2/3s; không gọi việc đổi timeout là cải thiện thuật toán.
Tách ablation tracking / entry / temporal và khóa lựa chọn trên validation.
Offline all-frame replay và realtime latest-frame là hai chế độ khác nhau: báo riêng.
Không tái sử dụng frame hoặc lặp video để làm đủ cửa sổ xác nhận.

trace_to_windows() trong metrics.py tạo bin 1s, không look-ahead hoặc forward-fill ALERT.
model_frame_available=true chỉ khi có fresh successful inference, kể cả model không thấy tay.
Một bin available khi có >=1 frame model hợp lệ trong bin; ghi fresh_frame_count và nhịp thực.
Không có frame hợp lệ -> unavailable, không điền no_contact.
Binarization: positive nếu có state ALERT trong các quan sát hợp lệ của bin.
Tay mất detection nhưng model đã chạy là quan sát hợp lệ của trạng thái thuật toán,
còn camera/model không cung cấp frame là unavailable.
Không dùng nhãn thật để quyết định prediction, sampling, loại frame hoặc chọn threshold.

## Metric classification

Grid 1s cố định từ đầu clip; bin cuối ngắn vẫn là một mẫu và được ghi end time thực.
Any contact overlap -> target positive. Bin chồng uncertain -> unknown và báo riêng.
Confusion rows actual contact/no_contact, columns predicted contact/no_contact/unavailable:
[[TP,FN,U_pos],[FP,TN,U_neg]].
Khi coverage đầy đủ:
Accuracy=(TP+TN)/(TP+TN+FP+FN)
Precision=TP/(TP+FP)
Recall=TP/(TP+FN)
F1=2TP/(2TP+FP+FN).
Mẫu số 0 -> null, không tự đặt 100%.
Thiếu prediction -> primary metric null/BLOCKED; available-only chỉ là diagnostic.
Báo unknown exposure và class prevalence. Không loại camera dropout khỏi báo cáo để nâng Accuracy.
Tỷ lệ uncertain >5% hoặc thiếu một class -> chưa đủ điều kiện xét mục tiêu.
Báo kết quả theo scenario/session, không chỉ pooled average bị nền âm chi phối.

## Event, latency và false alerts/hour

GT event là physical contact, predicted event là một lần phát alert.
Ghép cùng video/tác phẩm, one-to-one maximum cardinality, deterministic.
Mặc định không cho trigger trước onset; trigger được phép đến min(end+0.5s,onset+2s).
Tolerances phải được khóa trước test. Duplicate alert không ghép được tính FP.
FN là GT event không có alert ghép; event không có TN/Accuracy chuẩn.
Overlap hai tay có thể làm identity/latency attribution mơ hồ; lưu pair và stratify cảnh đó.

FA/hour = số predicted events không ghép được / tổng giờ known monitoring footage.
Đếm cả duplicate alert; loại uncertain triggers nhưng báo số loại và exposure rõ ràng.
Không gọi đây là tỷ lệ chỉ trên giờ âm; negative_seconds được báo riêng.
Coverage thiếu thì event counts là diagnostic; không dùng hệ thống đang offline để tuyên bố FA/hour thấp.

Source confirmation delay = trigger_source_seconds - physical onset.
Emission delay = emitted_elapsed_seconds - physical onset chỉ khi hai clock đã căn chỉnh.
Source delay offline KHÔNG phải latency camera-to-website.
Báo median/p95, số event có clock hợp lệ, missed events và độ bất định annotation;
không báo latency chỉ trên TP mà giấu FN.
Benchmark thật cần tách acquisition/decode, CPU transfer, hai stream GPU, temporal,
encode/I/O; warm-up và CUDA synchronization phải được ghi rõ sau phê duyệt inference.

## Thống kê và kiểm soát công bố

Lưu input/prediction/protocol/model/config/source hashes, Python/env metadata và logs rejection.
Báo số phiên/người/tranh, positive/negative duration và contact events.
Ước lượng 95% CI bằng bootstrap theo session/capture group với seed cố định,
không coi hàng nghìn frame liên tiếp là hàng nghìn mẫu độc lập.
Hiện tool chuẩn bị point metrics, CI chưa triển khai/chưa tính vì chưa có dữ liệu thật.
Không tuyên bố đạt >80% chỉ từ arithmetic unit tests, controlled scenarios hoặc vài clip.
Không sửa tham số sau xem test; nếu sửa phải có test holdout mới.
