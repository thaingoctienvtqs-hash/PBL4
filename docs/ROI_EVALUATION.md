# ROI calibration and video evaluation

## Calibrate the painting area

Use a real frame from the installed camera position. The calibrator supports a
sample image or one JPEG request to the ESP32-CAM `/capture` endpoint:

```powershell
python -m src.calibrate_roi --image .\data\camera_frame.jpg
python -m src.calibrate_roi --camera-url http://<ESP32-CAM-IP>/capture
```

Alternatively, omit `--camera-url` after setting `PBL4_CAMERA_URL`, or pass
`--config path\to\pbl4.json` to select the settings file. The camera option
uses the existing `fetch_jpeg` service and makes one request; it does not open a
second video stream. Stop any camera capture/worker while calibrating so only
one process is requesting frames.

Click the four painting corners in the preview. Press **Enter** to inspect and
save the outline, **U** to undo a point, **R** to start again, or **Esc** to
cancel without changing configuration. Points are stored in perimeter order as
normalized `[x, y]` values in the 0–1 range. The default `polygon` shape handles
a convex perspective view. Use `--shape rectangle` only when an axis-aligned
rectangle is appropriate. Invalid, crossed, concave, or degenerate selections
are rejected. ROI remains disabled by default until calibration is confirmed.

Settings are saved atomically in the selected PBL4 JSON config. The dashboard
disables rectangle coordinate editing while a polygon is active and shows how
to recalibrate it. The realtime worker draws the configured ROI, hand boxes,
track IDs, Object-Contact score, ROI overlap, and temporal state on its latest
frame preview.

## Realtime camera check

After calibration, run one worker against the configured ESP32-CAM stream:

```powershell
$env:PBL4_CAMERA_URL = 'http://<ESP32-CAM-IP>/capture'
python -m src.realtime_worker --mode camera --device cuda
```

The worker requests one JPEG per polling interval through the existing camera
service. For the Windows capture plus WSL inference arrangement, use the
existing `esp32cam_capture.py` and `file-watch` instructions in `SETUP.md`;
do not run both capture paths at once. Confirm the ROI outline and the hand
labels in the dashboard's latest-frame preview. A disconnected camera should
report `CAMERA_DISCONNECTED`; reconnection starts fresh tracks.

## Record and review labeled videos

Use a fixed camera and leave the painting, camera position, resolution, and
lighting unchanged after ROI calibration. Record separate real clips for:

1. A person standing near the painting without touching it.
2. A hand moving from outside the ROI into it without contact.
3. A real touch followed by a stationary hold, long enough to cover the alert
   confirmation and clear intervals.
4. A hand already depicted in the painting with no person present.
5. A real hand remaining outside the ROI.
6. A camera interruption followed by reconnection, if that can be recorded
   safely in the actual installation.

Have a human annotator record the true touch intervals separately from the
model output. A suitable CSV header is:

```text
video,scenario,start_seconds,end_seconds,person_present,physical_touch,notes
```

Use one row per labeled interval and preserve original videos. Record camera
resolution, frame rate, ROI config, and model checkpoint alongside the labels.
Do not infer physical contact from an Object-Contact score.

Replay a labeled clip through the same temporal worker logic in video timestamp
order:

```bash
python -m src.evaluate_video \
  --video /path/to/real_clip.mp4 \
  --output-video /path/to/results/real_clip_annotated.mp4 \
  --report-jsonl /path/to/results/real_clip_predictions.jsonl \
  --device cuda
```

The replay writes an annotated video and one JSON record per frame, including
hand boxes, scores, ROI overlap, track state, and event IDs. It uses a temporary
event store and does not overwrite live runtime status, database, evidence, or
the input video. It does **not** calculate precision, recall, false-positive
rate, or real-time latency. Those require comparing the per-frame output to
human labels and measuring a live camera run separately.

ContactHands only provides visual model scores. It cannot always distinguish a
real hand from a depicted hand or prove physical touch from a single camera
view. Keep these ambiguous cases labeled for human review rather than counting
them as verified events.
