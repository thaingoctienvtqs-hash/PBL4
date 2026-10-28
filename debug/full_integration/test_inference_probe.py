"""SYNTHETIC_TEST safety gates only; no model/GPU imports or inference."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from . import inference_probe as m


class InferenceProbeSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='artguard_probe_SYNTHETIC_TEST_')
        self.root = Path(self.temp.name)
        self.image = self.root / 'fixture_SYNTHETIC_TEST.jpg'; self.image.write_bytes(b'TEST')
        self.second = self.root / 'fixture_NOT_MODEL.pkl'; self.second.write_bytes(b'TEST')

    def tearDown(self):
        self.temp.cleanup()

    def test_missing_optin_never_runs_inference(self):
        with patch.object(m, 'run_probe') as run, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as exc:
                m.main(['--run-root', str(self.root), '--image', str(self.image),
                        '--second-stream-weights', str(self.second)])
        self.assertEqual(exc.exception.code, 2)
        run.assert_not_called()

    def test_internal_output_root_rejected(self):
        with self.assertRaises(ValueError):
            m.preflight(m.REPO, [self.image], self.second, 1)

    def test_bounds_rejected_before_checkpoint_hash(self):
        for images, repeat in (([], 1), ([self.image] * 3, 1), ([self.image], 0), ([self.image], 3)):
            with self.subTest(repeat=repeat), patch.object(m, 'digest') as digest:
                with self.assertRaises(ValueError):
                    m.preflight(self.root, images, self.second, repeat)
                digest.assert_not_called()

    def test_missing_local_weights_no_uri_fallback(self):
        with self.assertRaises(ValueError):
            m.preflight(self.root, [self.image], 'https://example.com/model.pkl', 1)

    def test_unexpected_checkpoint_hash_refused(self):
        with patch.object(m, 'digest', return_value='0' * 64):
            with self.assertRaises(ValueError):
                m.preflight(self.root, [self.image], self.second, 1)

    def test_protected_manifest_covers_existing_inputs_and_weights(self):
        with patch.object(m, 'digest', return_value=m.EXPECTED_FIRST_SHA):
            root, images, first, second, hashes = m.preflight(self.root, [self.image], self.second, 1)
        self.assertEqual(root, self.root)
        self.assertIn(str(self.image), hashes)
        self.assertIn(str(first), hashes)
        self.assertIn(str(second), hashes)
        self.assertEqual(len(hashes), 7)
        self.assertCountEqual(list(self.root.iterdir()), [self.image, self.second])


if __name__ == '__main__':
    unittest.main()
