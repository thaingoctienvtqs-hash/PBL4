# ArtGuard — Các ứng viên cần rà soát, chưa được phép xóa

Đối chiếu source/hash ngày 18/10/2026. Đây là danh sách điều tra và ưu tiên giảm rủi ro, **không phải danh sách xóa**. Nhóm 1 chỉ thêm tài liệu; không sửa bất kỳ ứng viên nào.

## Mức tin cậy và nguyên tắc

- **Cao về bằng chứng**: cùng SHA-256 hoặc thấy trực tiếp symbol/đường gọi không khớp. Không có nghĩa xóa an toàn.
- **Trung bình**: tìm tham chiếu tĩnh trong phạm vi đã rà soát; có thể thiếu caller ngoài repo/dynamic import.
- **Thấp / chưa biết**: chưa biết nguồn gốc, chủ sở hữu hoặc workflow đang dùng.
- Độ rủi ro nếu xóa đánh giá riêng: Low/Medium/High/Critical. Không có caller tĩnh không phải bằng chứng file không dùng.

## Nội dung trùng hoặc các bản chuyển tiếp

| Ứng viên | Bằng chứng và tin cậy | Rủi ro nếu xóa / điều kiện trước mọi đề xuất |
|---|---|---|
| [recovered](../../src/realtime_worker_recovered.py), [verified](../../src/realtime_worker_verified.py), file root `bject Name,Length,LastWriteTime` | **Cao**: cả ba 25.781 byte, cùng SHA-256; file tên lạ thực tế chứa Python worker, không phải output liệt kê thư mục | **High**: có thể là bản phục hồi/caller ngoài repo; cần xác nhận chủ sở hữu, archive riêng và inventory launcher trước; hiện giữ nguyên |
| [integrated](../../src/realtime_worker_integrated.py), [v2](../../src/realtime_worker_integrated_v2.py), [v3](../../src/realtime_worker_integrated_v3.py) | **Cao**: nhiều hàm giống nhau, các bước đổi import khác nhau; không phải ba file hoàn toàn giống | **High**: v3 là baseline được diagnostics import; không gộp hoặc thay alias trong Nhóm 1 |
| [realtime_worker.py](../../src/realtime_worker.py), [bản .bak](../../src/realtime_worker.py.bak) | **Cao**: file .py hiện 0 byte; .bak 2.156 byte. Tài liệu cũ còn nhắc tên entrypoint | **Medium/High**: rỗng không đồng nghĩa xóa an toàn; .bak có thể là dữ liệu khôi phục duy nhất |
| [index.html gốc](../../index.html) và [React index](../../web/frontend/index.html) | **Cao**: hai dashboard khác nhau; launcher cũ vẫn dùng HTML gốc | **High**: không phải duplicate có thể thay thế; giữ cả hai tới khi workflow cũ được chính thức ngừng |
| Cặp wrapper/config/camera cũ và compat | **Cao**: API khác nhau, còn caller riêng | **High**: không gộp chỉ dựa tên giống nhau; cần adapter contract và regression riêng |
| Phase B/C/D/E/F và các bản schema | **Cao**: có kế thừa, golden inputs và báo cáo lịch sử | **High**: đây là đối chứng thí nghiệm; không dọn theo số lượng ALERT hoặc kết quả FAIL |

SHA-256 của bộ ba recovered/verified/file root:
`c538fe183023933cf93351e65a08d87db960433960a3fbf54e526765a42f5e4e`.

Chuỗi sửa import quan sát được: recovered/verified dùng camera và config cũ; integrated chuyển camera_compat; v2 chuyển config_compat; v3 chuyển contacthands_compat. V2 vẫn truyền second_stream/device vào constructor cũ không nhận các keyword đó ([v2](../../src/realtime_worker_integrated_v2.py), dòng 333–343; [wrapper cũ](../../src/core/contacthands.py), dòng 15–20). Đây là lỗi hợp đồng theo source, chưa chạy runtime để tạo traceback trong lượt này.

## Import/khai báo có thể dư: chỉ đề nghị kiểm tra nhỏ

| Vị trí | Bằng chứng tĩnh | Độ tin cậy / rủi ro / bước xác minh |
|---|---|---|
| [inference/dataset_collector.py](../../inference/dataset_collector.py), dòng 5: `os`; dòng 12: `DEFAULT_FPS` | Không thấy sử dụng tên sau import trong file hiện tại | Cao về local usage, **Low** nếu chỉ bỏ import sau duyệt; kiểm tra AST, caller và test không mở camera trước |
| [src/yolo_pipeline.py](../../src/yolo_pipeline.py), dòng 14: `cv2` | Không thấy tham chiếu cv2 trong phần logic | Cao về local usage, **Medium** vì module có runtime setup/import khác; không import để “thử” trong audit |
| [web/backend/app/api/evidence.py](../../web/backend/app/api/evidence.py), dòng 17/20: `os`, `BytesIO`; dòng 33: `Artwork`, `Device` | Chưa thấy tên được dùng trong file theo rà soát tĩnh | Trung bình/Cao, **Medium**: API evidence đang được đăng ký, phải giữ route và kiểm tra hợp đồng/ORM trước |
| [src/detect_compat.py](../../src/detect_compat.py), dòng 10/15: import MetadataCatalog lặp | Cùng import được khai báo hai lần | Cao, **High** nếu kéo theo “tối ưu import” cả registry/torch; chỉ xem xét thay đổi một dòng sau duyệt riêng |

Không bỏ star import/model registration hoặc migration import models vì công cụ lint đánh dấu “unused”. Xem [DEPENDENCIES](DEPENDENCIES.vi.md).

## Chưa tìm thấy caller: giữ ở mức nghi vấn

| Vị trí | Kết quả rà soát | Hành động phù hợp |
|---|---|---|
| [CameraLiveView.tsx](../../web/frontend/src/components/CameraLiveView.tsx), dòng 44 | Export tồn tại, chưa thấy incoming import từ cây React hiện tại | Tin cậy Trung bình, rủi ro **Medium**: có thể tính năng chuẩn bị; xác nhận với nhóm frontend, không xóa |
| [client.ts](../../web/frontend/src/api/client.ts), hàm uploadEvidenceMedia | Export chưa thấy caller hiện tại | Trung bình, **Medium**: có thể dành tích hợp evidence sắp tới |
| [alignment helper](../../src/contact_hands_two_stream/engine/second_stream_alignment.py) | Không phải đường inference chính, nhưng [test](../../tests/test_two_stream_alignment.py), dòng 34/124/144 nạp bằng importlib | Có caller đã xác nhận; **High**, loại khỏi ứng viên xóa theo “không dùng” |
| Các tool acquire/train/synthetic và CLI | Không nhất thiết có import vào app | Chưa đủ căn cứ: CLI là caller độc lập; rủi ro **High**, không chạy/download/train để điều tra |
| Bytecode __pycache__ mang tên source không còn thấy | Chưa biết có phục vụ phục hồi source hay không | **Thấp** về khả năng bỏ; không purge tự động |
| Ảnh camera, tên file bất thường, evidence, history, DB và thư mục data | Thiếu nhãn nguồn gốc/owner | **High/Critical**: có thể là dữ liệu thực nghiệm duy nhất; không gọi là rác |

## Dung lượng lớn không phải tiêu chí xóa

- `models/combined_data_model.pth` là checkpoint được bảo vệ.
- Object tương ứng trong `.git/lfs/objects` thuộc cơ chế Git LFS; không xóa bản “trùng” để tiết kiệm dung lượng.
- Git pack, node_modules, backend virtualenv, dataset, cache model và debug/runs đều cần chính sách riêng. Không git gc/clean, npm install, tái tạo môi trường hoặc purge trong Nhóm 1.
- `web/.env.example` và `web/frontend/package-lock.json` đã có thay đổi trước đó; không “sửa tiện” newline, pin phiên bản hoặc format.
- Không đưa `start_pbl4.bat` vào nhóm xóa: ghi rõ LEGACY rồi xin quyết định workflow từ nhóm.

**Đề xuất nhỏ nhất cho lượt sau:** xin duyệt kiểm tra và bỏ duy nhất import `os` không dùng ở dataset_collector, kèm static check và test phù hợp không mở camera. Chưa thực hiện. Mọi xóa file vẫn phải chứng minh an toàn và xin duyệt riêng theo [kế hoạch](SAFE_REFACTOR_PLAN.vi.md).
