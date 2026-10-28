# ArtGuard — kết quả khôi phục tích hợp phần mềm (28/10/2026)

## Kết luận và giới hạn

| Phạm vi | Trạng thái | Bằng chứng |
|---|---|---|
| SOFTWARE INTEGRATION | PARTIAL | Sender → FastAPI → SQL TEST và HTTP qua Vite PASS; UI render/polling trong browser chưa xác minh |
| SYNTHETIC SOFTWARE E2E | PARTIAL | EventStore/outbox/API/SQL/query/evidence PASS; browser E2E BLOCKED |
| OFFLINE AI TEST | PASS | 2 JPEG có sẵn × 2 lượt ContactHands CUDA, không chạy ALERT |
| HARDWARE E2E | NOT TESTED — NO HARDWARE | Không truy cập ESP32-CAM hoặc IP cũ |

Không có dữ liệu độc lập có nhãn để kết luận Accuracy >80%, Precision/Recall/F1 ≥80%. Không đo latency chạm tranh → ALERT. Camera offline ở phiên này là điều kiện thử nghiệm, không phải lỗi hệ thống.

## Trạng thái ban đầu và khôi phục

Branch `test-web`, HEAD `d194f29e6136b831633046072f8ca9ed88c55fcf`. Working tree sạch trước sửa; đã đọc lịch sử commit. Backup commit không đồng nghĩa phần mềm đã hoàn thiện.

Audit đầu phiên:
- DONE: reader/outbox và backend ingest đã có source; Step A giữ nguyên.
- PARTIAL: chưa có regression sender/ingest, frontend helpers bị bỏ rời, trang Dashboard/Alerts chưa polling.
- NOT STARTED: migration 0003, launcher, SQL runtime integration/E2E tests.
- SQL TEST: DB/user có sẵn, chưa có bảng. Đã xác minh đúng identity trước ghi.
- HARDWARE: không có; không chờ hoặc gọi camera.

Backup mới trước sửa:
`C:\Users\LEGION\ArtGuard-FullIntegration-Backup\resume_20261028T093118720743Z_46cdffd7`.
Manifest SHA-256 bao phủ 15.368 file có sẵn (ngoài .git), cùng bản sao raw các vùng tích hợp.

RUN:
`C:\Users\LEGION\ArtGuard-FullIntegration-Test\resume_20261028T093118720743Z_46cdffd7`.

## Những phần đã hoàn thiện

1. Sender: reader SQLite mode=ro/query_only, payload/event ID ổn định, sidecar ACK/retry, backoff, restart, giữ lỗi hết retry. Requeue phải tường minh; không tự gửi lại event DELIVERED hoặc bỏ qua AUTH_BLOCKED. Chấp nhận ACK MISSING nhưng không gọi ảnh READY. Lỗi HTTP vĩnh viễn được quarantine.
2. Ingest: producer key riêng, origin/instance/artwork/device scope, Pydantic, giới hạn metadata 64KiB trước parse kể cả chunked, UTC canonical hash, unique receipt và transaction Alert/Evidence/history/audit. Replay 200; payload khác cùng ID 409.
3. Evidence: raw JPEG upload có hash, path do server sinh, 5MiB, xác minh JPEG, no overwrite, media ACK có schema_version/data_origin. Evidence API Step A source không sửa.
4. SQL TEST: migration bổ sung không phá hủy, user/session DML, seed tối thiểu chỉ TEST. Không bật migration/seed của production.
5. React: dùng lại usePolling/AlertEvidence/datetime; polling 2 giây sau completion, abort và chống request chồng; batch provenance, trạng thái TEST/API, UTC, evidence blob có auth. DEMO/SYNTHETIC_TEST/REAL_AI/UNVERIFIED rõ ràng. Không đổi auth hoặc thiết kế trang.
6. Launcher: loopback riêng, logs/cache external, bootstrap success gate, PID/creation-time/command-line identity trước stop; không kill theo tên. start/stop độc lập backend/frontend.
7. Runner regression và synthetic E2E tái lập; nguồn synthetic dùng chung namespace và source ID tăng dần. Không sửa row cũ khi append. Nguồn không xác minh hoặc mất DB bị từ chối thay vì tạo lại dưới identity cũ.

## SQL Server TEST thực tế

Đã xác minh `DESKTOP-2K5T32D\SQLEXPRESS`, `127.0.0.1:56929`, `ArtGuard_Integration_TEST`, đúng database_id/create_date lịch sử.

Migration head: `0003_ai_event_receipts`. Có 19 bảng, gồm ai_event_receipts/ai_event_attachments/alerts/evidences/evidence_media. Sau test: 2 receipt, 2 alert, 2 evidence, 2 attachment/media; 3 tài khoản TEST, 1 artwork, 1 device offline. Không seed sự kiện REAL_AI.

Windows login vẫn là sysadmin; session ứng dụng dùng `EXECUTE AS USER artguard_integration_app`, không db_owner, không CREATE TABLE. Đây là giới hạn session, **không phải credential quyền thấp độc lập**. Chưa sẵn sàng triển khai production với identity này.

Đã đọc đối chiếu số hàng production: khớp baseline lịch sử ở cả 17 bảng; không phát lệnh ghi production. So số hàng không phải kiểm chứng byte-for-byte toàn DB.

Lỗi gặp và đã sửa: SQLAlchemy MSSQL không hỗ trợ get_unique_constraints. Lần bootstrap lỗi đã rollback; xác minh bảng vẫn rỗng trước retry. Migration dùng sys catalog; TEST admin dùng unique indexes. Retry thành công, không xóa/recreate DB.

## Kiểm thử thực tế

| Bộ kiểm thử | PASS | FAIL |
|---|---:|---:|
| Step A core | 38 | 0 |
| Step A HTTP | 45 | 0 |
| AI ingest core/migration | 25 | 0 |
| AI ingest ASGI HTTP | 27 | 0 |
| Sender/camera giả lập/worker preflight/probe safety | 46 | 0 |
| Launcher + synthetic prepare regression | 15 | 0 |
| Frontend helpers offline | 15 | 0 |
| SQL TEST runtime, có transaction rollback | 4 | 0 |
| **Tổng regression chọn lọc** | **215** | **0** |

Log đầy đủ:
`RUN\checks_20261028T094710964113Z\summary.json`.
Không chạy pytest toàn repository. 46 test logic sender/probe cũng PASS trên WSL Python 3.7.16; không cộng lặp vào tổng215.

TypeScript app/config noEmit PASS; Vite build PASS (2.328 modules), output `RUN\frontend_dist_verified`. git diff --check PASS. Không cài package, không tự chuẩn hóa newline.

Lần chạy Step A trong sandbox ban đầu bị chặn đọc HTTPX và Python platform fallback; chạy lại với quyền runtime thông thường PASS, giữ nguyên test/guard. Không coi lỗi sandbox là lỗi chức năng Evidence.

## Synthetic E2E và recovery thực tế

Nguồn là EventStore TEST mới, schema/hàm EventStore thật; ảnh ghi chữ SYNTHETIC_TEST. Không phải prediction AI.

- Source event1 → event UUID `f53deb2b-182b-5262-b1d2-96548197e08a` → receipt2 → alert1/evidence1.
- Source event2 → event UUID `0269b605-a2fa-50c5-b09f-58e6eb147f23` → receipt3 → alert2/evidence2.
- Mỗi case PASS 12 gate HTTP/SQL: exact replay, 4 request replay đồng thời cùng ID, conflict409, malformed422, producer401, synthetic→REAL_AI403, query provenance/alert, anonymous401, SQL identity và duy nhất một receipt, nguồn không bị sender ghi.
- Downtime thật: dừng đúng FastAPI TEST sở hữu, event2 giữ RETRY/network_error. Khởi động lại; cùng event ID chuyển DELIVERED ở attempt2; evidence DELIVERED. Không dừng SQL Server.
- HTTP qua Vite PASS: index và transformed React entry200, login200, alerts200(total2), Dashboard/artworks/devices/history/evidence200. Authenticated JPEG200 có hash khớp fixture; anonymous file401.

Lỗi helper đã sửa: prepare tạo SQLite mới ID1 trong cùng producer instance có thể đụng event UUID. Case chuẩn bị lỗi `synthetic_20261028T094148304290Z_419379c8` **không gửi**, được giữ nguyên làm artifact. Sau sửa, manifest chỉ một nguồn synthetic và ID tăng dần;7 regression test chứng minh row cũ không đổi.

Browser automation BLOCKED: browser host không khả dụng; native Computer Use dừng vì không xác định URL Chrome đủ chắc chắn để áp dụng policy. Đã dừng UI automation, không thử vượt guard. **Chưa xác minh React render, auto refresh hoặc DOM visibility trong browser**. HTTP/static build không được gọi là browser E2E PASS.

## Offline ContactHands CUDA

Dùng Python3.7.16, torch1.13.1+cu117, Detectron2 0.1.1 và detectron2._C hiện có, RTX4060. Hai JPEG có sẵn, mỗi ảnh2lượt, explicit weights local, network guard; không chạy worker/ROI/tracking/ALERT/EventStore.

- Model initialization: 10.862,0ms.
- First inference: 3.565,31ms.
- Subsequent inference: 115,74 / 87,13 / 80,25ms.
- camera_hand_test.jpg: 1 hand, detection0,99809, Object-Contact0,97592.
- Ảnh Mona Lisa lịch sử: không phát hiện tay. N=1 ảnh này không chứng minh chống false positive tổng quát.
- Peak allocated: 823.538.688byte.
- 8hash trước/sau khớp: hai checkpoint, source compat, configs, JPEGs.

Lần đầu native cuDNN/libcuda abort; giữ artifacts, không xóa. Retry thành công bằng LD_LIBRARY_PATH **chỉ trong process**:
`/usr/lib/wsl/lib:/home/legion/miniconda3/envs/contacthands/lib`,
không sửa Conda/CUDA, không cài lại thư viện. Dùng timeout180s và ulimit-c0.

Kết quả: `RUN\offline_inference_d842323068034c1592368b0f02a30b2d\result.json`.
Số đo là synchronized wall gồm preprocess/hai stream/postprocess, không phải CUDA kernel-only, không phải accuracy hoặc physical contact latency.

## Latency đã đo và còn thiếu

Event1: EventStore commit→outbox 13,84ms; event HTTP + outbox ACK 172,98ms; media HTTP + ACK79,08ms.
Event2 sau recovery: event HTTP + ACK162,20ms; media80,26ms.
Đây là vài observation, **không phải p50/p95 hoặc SLA**. API→SQL commit riêng chưa có instrumentation; không suy ra bằng cách trừ timestamp khác process.
Polling2s + request làm mục tiêu alert-visible300/500ms chưa được bảo đảm. Chưa đo Dashboard render, capture→decision, touch→ALERT hoặc false alerts/hour. Không hạ ngưỡng/temporal để tăng tốc.

## File thay đổi

10 file có sẵn:
- debug/full_integration/event_sender.py
- debug/full_integration/sql_test_admin.py
- web/backend/app/ai_event_schemas.py
- web/backend/app/api/ai_events.py
- web/backend/app/services/ai_event_ingest.py
- web/frontend/src/api/client.ts
- web/frontend/src/pages/AlertsPage.tsx
- web/frontend/src/pages/DashboardPage.tsx
- web/frontend/src/types.ts
- web/frontend/vite.config.ts

18 file mới:
- debug/full_integration/OPERATIONS.vi.md
- debug/full_integration/RESULTS.vi.md
- debug/full_integration/inference_probe.py
- debug/full_integration/launch_test.py
- debug/full_integration/run_checks.py
- debug/full_integration/software_e2e.py
- debug/full_integration/test_camera_receiver.py
- debug/full_integration/test_event_sender.py
- debug/full_integration/test_frontend_helpers.mjs
- debug/full_integration/test_inference_probe.py
- debug/full_integration/test_launch_test.py
- debug/full_integration/test_software_e2e.py
- debug/full_integration/test_sql_integration.py
- debug/full_integration/test_support.py
- debug/full_integration/test_worker_test_runner.py
- debug/minimal_demo/test_ai_event_ingest.py
- debug/minimal_demo/test_ai_event_ingest_http.py
- web/backend/migrations/versions/0003_ai_event_receipts.py

## Bảo vệ và Git

15.358/15.368 file có sẵn không đổi; đúng10file tích hợp thay đổi; missing0; out-of-scope0. Toàn bộ879file dưới debug/alert_diagnostics giữ hash. Checkpoint, v3, EventStore source, contact_logic, Evidence API + hai Step A tests, .env.example, package-lock giữ hash.

Checkpoint SHA-256:
`c03f38a947d426b39b7538a5478f823799d98b34e0fb299ec35a6520342a342a`.
Evidence API SHA-256:
`f927df968baedd5584e22351b8bd9974420b8a3893e5e16b698b963177ed2197`.

Full before/after hashes nằm trong manifest backup và RUN/logs/protection_*.json. Không sửa repo ContactHands gốc hoặc dataset ngoài Pbl4; không phát lệnh ghi dataset. Không làm full bytewise audit dataset ngoài repository; không khẳng định đã có hash-before/after cho toàn bộ dataset ngoài.

HEAD/branch giữ nguyên; không add/commit/push/reset/clean/restore/stash. Git chỉ có10modified và18untracked nêu trên. Không in secret, không thêm .env, không đổi package lock/môi trường.

## Xem và vận hành ngay

Đã xác minh HTTP backend/frontend đang chạy trên loopback:
- Website: http://127.0.0.1:5175
- Health: http://127.0.0.1:8101/health
- Dashboard: / ; Alerts: /alerts
- Login: integration_admin, integration_operator hoặc integration_viewer. Mật khẩu xem cục bộ trong RUN/private_test_credentials.json mục users; không đưa vào log/chat/Git.

Lệnh PowerShell từ C:\Users\LEGION\Pbl4:

```powershell
$Run = 'C:\Users\LEGION\ArtGuard-FullIntegration-Test\resume_20261028T093118720743Z_46cdffd7'
$Python = '.\web\backend\.venv\Scripts\python.exe'
& $Python -B -m debug.full_integration.launch_test --run-root $Run status
# Chỉ start khi dịch vụ chưa chạy; cổng có chủ sẽ được từ chối:
& $Python -B -m debug.full_integration.launch_test --run-root $Run start-backend
& $Python -B -m debug.full_integration.launch_test --run-root $Run start-frontend
# Tắt đúng hai service sở hữu, không dừng SQL Server hoặc xóa dữ liệu:
& $Python -B -m debug.full_integration.launch_test --run-root $Run stop-test
# Regression chọn lọc; không model/camera:
& $Python -B -m debug.full_integration.run_checks --run-root $Run --with-sql
```

Synthetic prepare/deliver/verify và checklist14bước hardware nằm trong [OPERATIONS.vi.md](OPERATIONS.vi.md). Script SQL admin hiện dùng để inspect/đã bootstrap đúng TEST; không dùng launcher/migration production.

## Còn lại trước khi hoàn thiện100%

1. Kiểm tra browser thủ công/automation sau khi guard URL hoạt động: login, Dashboard/Alerts, thêm synthetic event không refresh, evidence, error/empty/loading. Hiện chỉ API/build được chứng minh.
2. Đo server transaction và rendered-UI latency có clock contract/ack rõ. Không hứa300/500ms.
3. Khi có phần cứng: xác nhận nguồn/Wi-Fi/consumer, camera OV3660 gắn trực tiếp mép trên tranh nhìn xiên xuống; chụp mới và duyệt ROI, không tái dùng ROI cũ.
4. Kiểm thử real event→EventStore→sender→SQL TEST→UI với bề mặt mô phỏng và ground truth. Receiver/worker runner mới qua fake/preflight, chưa chạy hardware.
5. Đánh giá nhiều phiên video độc lập có nhãn, UNKNOWN/coverage, false positive/negative; khóa validation trước test. Không chứng minh mục tiêu80% bằng test logic.
6. Credential quyền thấp độc lập và triển khai production cần phê duyệt riêng. Không tự tích hợp vào DB production.
