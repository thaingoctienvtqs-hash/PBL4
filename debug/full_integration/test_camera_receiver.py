"""SYNTHETIC_TEST: fake JPEG transport, never contacts a camera."""
import io
import tempfile
import unittest
from pathlib import Path
from . import camera_receiver as m

JPEG_HEADER = b'\xff\xd8\xff\xc0\x00\x08\x08\x00\xf0\x01\x40\x01\xff\xd9'


class Response(io.BytesIO):
    status = 200
    headers = {'Content-Type': 'image/jpeg'}


class FakeOpener:
    def __init__(self, body=JPEG_HEADER):
        self.body, self.calls = body, []

    def open(self, request, timeout):
        self.calls.append((request.full_url, timeout))
        return Response(self.body)


class CameraTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='artguard_camera_SYNTHETIC_TEST_')
        self.root = Path(self.temp.name)
        self.opener = FakeOpener()

    def tearDown(self):
        self.temp.cleanup()

    def receiver(self, **kwargs):
        return m.CameraReceiver('http://127.0.0.1/capture', self.root, '127.0.0.1',
                                consumers_stopped=True, opener=self.opener, **kwargs)

    def test_missing_consumer_confirmation_refuses_before_io(self):
        with self.assertRaises(m.SafetyError):
            m.CameraReceiver('http://127.0.0.1/capture', self.root, '127.0.0.1', opener=self.opener)
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertEqual(self.opener.calls, [])

    def test_unconfirmed_host_stream_and_credentials_refused(self):
        for url in ('http://example.com/capture', 'http://127.0.0.1/stream',
                    'http://user:secret@127.0.0.1/capture', 'http://127.0.0.1/capture?x=1'):
            with self.subTest(url=url), self.assertRaises(m.SafetyError):
                m.CameraReceiver(url, self.root, '127.0.0.1', consumers_stopped=True, opener=self.opener)
        self.assertEqual(self.opener.calls, [])

    def test_fake_frame_atomic_publish_archive_and_unknown_capture_time(self):
        receiver = self.receiver()
        row = receiver.capture_once()
        self.assertEqual((row['width'], row['height']), (320, 240))
        self.assertEqual(row['source_capture_timestamp'], 'UNKNOWN')
        self.assertEqual(Path(row['archive']).read_bytes(), JPEG_HEADER)
        self.assertEqual(Path(row['published']).read_bytes(), JPEG_HEADER)
        self.assertEqual(len(self.opener.calls), 1)
        self.assertTrue((self.root / 'capture.jsonl').is_file())

    def test_preexisting_output_never_overwritten(self):
        target = self.root / 'capture_frame.jpg'
        target.write_bytes(b'KEEP')
        with self.assertRaises(m.SafetyError):
            self.receiver()
        self.assertEqual(target.read_bytes(), b'KEEP')
        self.assertEqual(self.opener.calls, [])

    def test_corrupt_frame_not_published(self):
        self.opener.body = b'not jpeg'
        receiver = self.receiver()
        with self.assertRaises(ValueError):
            receiver.capture_once()
        self.assertFalse((self.root / 'capture_frame.jpg').exists())

    def test_bounded_policy_rejected_before_capture(self):
        receiver = self.receiver()
        for kwargs in ({'max_frames': 0}, {'max_frames': 201}, {'interval': .01}, {'max_duration': 601}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                receiver.run(**kwargs)
        self.assertEqual(self.opener.calls, [])

    def test_jpeg_parser_rejects_bad_dimensions_and_segments(self):
        for data in (b'', b'\xff\xd8\xff\xc0\x00\x01\xff\xd9',
                     JPEG_HEADER.replace(b'\x00\xf0', b'\x00\x00')):
            with self.subTest(data=data), self.assertRaises(ValueError):
                m.jpeg_dimensions(data)


if __name__ == '__main__':
    unittest.main()
