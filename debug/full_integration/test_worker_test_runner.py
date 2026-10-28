"""SYNTHETIC_TEST preflight only. Never imports or starts original worker/model."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from . import worker_test_runner as m


class WorkerRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='artguard_worker_SYNTHETIC_TEST_')
        self.root = Path(self.temp.name)
        self.config = self.root / 'config.json'
        self.settings = {'paths': {key: str(self.root / key) for key in
            ('capture_frame', 'latest_frame', 'event_db', 'evidence_dir', 'status_file')},
            'roi': {'enabled': True, 'shape': 'polygon', 'normalized': True,
                    'points': [[.1, .1], [.9, .1], [.8, .9], [.2, .9]]},
            'hardware_session': {'roi_user_confirmed': True}, 'model': {}}
        for key in ('contacthands_config', 'contacthands_weights', 'second_stream_config', 'second_stream_weights'):
            path = self.root / (key + '.SYNTHETIC_TEST'); path.write_bytes(b'TEST_PLACEHOLDER_NOT_MODEL')
            self.settings['model'][key] = str(path)
        self.save()

    def save(self):
        self.config.write_text(json.dumps(self.settings), encoding='utf8')

    def tearDown(self):
        self.temp.cleanup()

    def test_build_command_original_worker_file_watch_only(self):
        root, command, env = m.build_command(self.root, self.config, interpreter='TEST_PYTHON')
        self.assertEqual(root, self.root)
        self.assertEqual(command[:4], ['TEST_PYTHON', '-B', '-m', 'src.realtime_worker_integrated_v3'])
        self.assertEqual(command[command.index('--mode') + 1], 'file-watch')
        self.assertNotIn('--max-frames', command)
        self.assertNotIn('--duration', command)
        for key in ('capture_frame', 'latest_frame', 'event_db', 'evidence_dir', 'status_file'):
            self.assertEqual(env['PBL4_' + key.upper()], self.settings['paths'][key])
        self.assertNotIn('PBL4_CAMERA_URL', env)

    def test_missing_explicit_config_refused(self):
        with self.assertRaises(m.SafetyError):
            m.build_command(self.root, self.root / 'missing.json')

    def test_unconfirmed_roi_refused(self):
        self.settings['hardware_session']['roi_user_confirmed'] = False; self.save()
        with self.assertRaises(m.SafetyError):
            m.build_command(self.root, self.config)

    def test_production_output_escape_refused(self):
        self.settings['paths']['event_db'] = str(self.root.parent / 'production.sqlite'); self.save()
        with self.assertRaises(m.SafetyError):
            m.build_command(self.root, self.config)

    def test_local_explicit_weights_required(self):
        self.settings['model']['second_stream_weights'] = 'https://example.com/model.pkl'; self.save()
        with self.assertRaises(m.SafetyError):
            m.build_command(self.root, self.config)

    def test_no_separate_approval_never_starts_process(self):
        with patch.object(m.subprocess, 'Popen') as popen:
            with self.assertRaises(m.SafetyError):
                m.run_worker(self.root, self.config)
        popen.assert_not_called()

    def test_stop_already_exited_does_not_signal(self):
        class Process:
            def poll(self): return 0
            def send_signal(self, value): raise AssertionError('must not signal')
        self.assertEqual(m.stop_owned_process(Process()), 'already_exited')


if __name__ == '__main__':
    unittest.main()
