"""Bounded Windows camera receiver for a separately approved TEST session.
Import is inert. No stream/control request, no camera configuration changes.
"""
import argparse
import io
import json
import os
import struct
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler
from .event_sender import REPO, NoRedirect, SafetyError, inside, controlled_path, canonical, sha

MAX_FRAME = 8 * 1024 * 1024


def jpeg_dimensions(data):
    if not data.startswith(b"\xff\xd8\xff") or not data.rstrip().endswith(b"\xff\xd9"):
        raise ValueError("not_complete_jpeg")
    offset = 2
    while offset < len(data) - 3:
        if data[offset] != 255:
            offset += 1
            continue
        while offset < len(data) and data[offset] == 255:
            offset += 1
        marker = data[offset]
        offset += 1
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            continue
        if offset + 2 > len(data):
            break
        length = struct.unpack(">H", data[offset:offset + 2])[0]
        if length < 2 or offset + length > len(data):
            raise ValueError("invalid_jpeg_segment")
        if marker in (0xC0, 0xC1, 0xC2, 0xC3):
            if length < 8:
                raise ValueError("invalid_jpeg_sof")
            height, width = struct.unpack(">HH", data[offset + 3:offset + 7])
            if not 1 <= width <= 8192 or not 1 <= height <= 8192:
                raise ValueError("invalid_jpeg_dimensions")
            return width, height
        offset += length
    raise ValueError("jpeg_dimensions_unavailable")


class CameraReceiver:
    def __init__(self, url, test_root, confirmed_host, consumers_stopped=False,
                 opener=None, clock=time.perf_counter, wall=time.time, sleep=time.sleep):
        root = Path(test_root).expanduser().resolve()
        if not root.is_dir() or inside(root, REPO) or inside(REPO, root):
            raise SafetyError("external_test_root_required")
        if consumers_stopped is not True:
            raise SafetyError("consumer_confirmation_required")
        parsed = urlsplit(url)
        if parsed.scheme != "http" or parsed.hostname != confirmed_host or parsed.port not in (None, 80):
            raise SafetyError("camera_target_not_confirmed")
        if parsed.path != "/capture" or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise SafetyError("only_confirmed_capture_endpoint_allowed")
        self.root, self.url = root, url
        self.clock, self.wall, self.sleep = clock, wall, sleep
        self.opener = opener or build_opener(ProxyHandler({}), NoRedirect())
        self.publish = controlled_path(root / "capture_frame.jpg", root)
        self.log = root / "capture.jsonl"
        if self.publish.exists() or self.log.exists():
            raise SafetyError("preexisting_capture_outputs_refused")
        self.log.open("x", encoding="utf8").close()
        self.count = 0

    def capture_once(self, timeout=5):
        if not 0 < float(timeout) <= 30:
            raise ValueError("invalid_timeout")
        start = self.clock()
        request_wall = self.wall()
        request = Request(self.url, headers={"Connection": "close", "Cache-Control": "no-cache",
                                          "User-Agent": "ArtGuard-TEST-Receiver/1"})
        with self.opener.open(request, timeout=float(timeout)) as response:
            if response.status != 200:
                raise RuntimeError("camera_http_not_200")
            content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if content_type != "image/jpeg":
                raise RuntimeError("camera_not_jpeg_content_type")
            data = response.read(MAX_FRAME + 1)
        receive = self.clock()
        if len(data) > MAX_FRAME:
            raise RuntimeError("camera_frame_too_large")
        width, height = jpeg_dimensions(data)
        self.count += 1
        archive = self.root / ("frame_{:06d}_{}.jpg".format(self.count, uuid.uuid4().hex))
        with archive.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temporary = self.root / ("publish_{}.tmp".format(uuid.uuid4().hex))
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        # Only the shared file first created by THIS receiver may be replaced.
        if self.count == 1 and self.publish.exists():
            raise SafetyError("capture_publish_appeared_concurrently")
        os.replace(str(temporary), str(self.publish))
        record = {
            "frame_id": self.count, "pid": os.getpid(), "source_capture_timestamp": "UNKNOWN",
            "host_request_time_unix": request_wall, "request_receive_ms": (receive - start) * 1000,
            "request_publish_ms": (self.clock() - start) * 1000,
            "width": width, "height": height, "bytes": len(data), "sha256": sha(data),
            "archive": str(archive), "published": str(self.publish),
        }
        with self.log.open("a", encoding="utf8") as handle:
            handle.write(canonical(record) + "\n")
        return record

    def run(self, max_frames=1, interval=1.0, max_duration=15.0, timeout=5.0):
        if not 1 <= int(max_frames) <= 200 or not .5 <= float(interval) <= 60 or not 1 <= float(max_duration) <= 600:
            raise ValueError("bounded_capture_policy_required")
        start = self.clock()
        records = []
        for index in range(int(max_frames)):
            if self.clock() - start >= max_duration:
                break
            records.append(self.capture_once(timeout))
            if index + 1 < max_frames:
                remaining = max_duration - (self.clock() - start)
                if remaining <= 0:
                    break
                self.sleep(min(interval, remaining))
        return records


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--confirmed-host", required=True)
    parser.add_argument("--test-root", required=True)
    parser.add_argument("--consumers-stopped-and-capture-approved", action="store_true")
    parser.add_argument("--max-frames", type=int, default=1)
    parser.add_argument("--interval-seconds", type=float, default=1)
    parser.add_argument("--duration-seconds", type=float, default=15)
    parser.add_argument("--timeout-seconds", type=float, default=5)
    args = parser.parse_args(argv)
    receiver = CameraReceiver(args.url, args.test_root, args.confirmed_host,
                              args.consumers_stopped_and_capture_approved)
    records = receiver.run(args.max_frames, args.interval_seconds, args.duration_seconds, args.timeout_seconds)
    print(canonical({"pid": os.getpid(), "captured": len(records), "source_fps": "UNKNOWN",
                     "note": "request cadence is not sensor FPS"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
