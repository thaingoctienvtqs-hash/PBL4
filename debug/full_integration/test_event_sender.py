"""SYNTHETIC_TEST only. No network, camera, model or server database."""
import copy
import hashlib
import json
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import patch
from . import event_sender as m


@contextmanager
def connect(path):
    db = sqlite3.connect(str(path))
    try:
        with db:
            yield db
    finally:
        db.close()


class FakeTransport:
    def __init__(self):
        self.calls = []
        self.failure = None
        self.mutate = None

    def request(self, path, body, content_type, extra_headers=None):
        self.calls.append((path, body, content_type, extra_headers))
        if self.failure:
            raise self.failure
        if path.endswith('/evidence'):
            payload = self.payload
            media = True
        else:
            payload = json.loads(body.decode('utf8'))
            self.payload = payload
            media = False
        ack = {'schema_version': '1', 'event_id': payload['event_id'],
               'producer_id': payload['producer_id'], 'data_origin': payload['data_origin'],
               'receipt_id': 1, 'alert_id': 2, 'evidence_id': 3,
               'replayed': False, 'evidence_status': 'READY' if media else 'PENDING'}
        if media:
            ack['media_id'] = 4
        if self.mutate:
            self.mutate(ack)
        return 201, ack


class SenderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='artguard_sender_SYNTHETIC_TEST_')
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.sqlite'
        with connect(self.source) as db:
            db.execute('CREATE TABLE events(id INTEGER PRIMARY KEY AUTOINCREMENT,timestamp REAL NOT NULL,kind TEXT NOT NULL,status TEXT NOT NULL,details_json TEXT NOT NULL,evidence_path TEXT)')
        self.cfg = m.validate_config({'profile': 'TEST', 'test_root': str(self.root),
            'source_db': str(self.source), 'outbox_db': str(self.root / 'outbox.sqlite'),
            'producer_id': 'unit-synthetic', 'producer_instance_id': str(uuid.uuid4()),
            'data_origin': 'SYNTHETIC_TEST', 'backend_url': m.BACKEND,
            'max_attempts': 3, 'retry_base_seconds': 1, 'retry_cap_seconds': 10})
        self.reader = m.ReadOnlyEventReader(self.source)
        self.outbox = m.SidecarOutbox(self.cfg, self.reader)
        self.transport = FakeTransport()
        self.now = 1000.0
        self.sender = m.Sender(self.cfg, self.outbox, self.transport, clock=lambda: self.now)

    def tearDown(self):
        self.temp.cleanup()

    def add(self, details=None, kind=m.EVENT_TYPE, timestamp=1700000000, evidence=None):
        if details is None:
            details = {'alert_at': '2026-10-28T10:00:00Z', 'object_contact_score': .91}
        with connect(self.source) as db:
            cursor = db.execute('INSERT INTO events(timestamp,kind,status,details_json,evidence_path) VALUES(?,?,?,?,?)',
                (timestamp, kind, 'OPEN', json.dumps(details), evidence))
            return cursor.lastrowid

    def queue(self):
        self.add()
        self.assertEqual(self.outbox.enqueue(), 1)
        return self.outbox.rows()[0]

    def test_reader_missing_file_does_not_create(self):
        path = self.root / 'missing.sqlite'
        with self.assertRaises(m.SafetyError):
            m.ReadOnlyEventReader(path)
        self.assertFalse(path.exists())

    def test_reader_schema_mismatch_rejected(self):
        path = self.root / 'wrong.sqlite'
        with connect(path) as db:
            db.execute('CREATE TABLE events(id INTEGER)')
        with self.assertRaises(m.SafetyError):
            m.ReadOnlyEventReader(path)

    def test_reader_query_only_and_ascending_cursor(self):
        self.add(); self.add(); self.add()
        before = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.assertEqual([r['id'] for r in self.reader.after(1, 2)], [2, 3])
        with self.reader.connect() as db:
            with self.assertRaises(sqlite3.OperationalError):
                db.execute('DELETE FROM events')
        self.assertEqual(before, hashlib.sha256(self.source.read_bytes()).hexdigest())

    def test_enqueue_and_restart_preserve_stable_identity(self):
        row = self.queue()
        again = m.SidecarOutbox(self.cfg, self.reader)
        self.assertEqual(again.enqueue(), 0)
        self.assertEqual(again.cursor(), 1)
        self.assertEqual(row, again.rows()[0])

    def test_enqueue_cursor_and_payload_rollback_atomically(self):
        self.add()
        def crash():
            raise RuntimeError('simulated_before_commit')
        with self.assertRaises(RuntimeError):
            self.outbox.enqueue(before_commit=crash)
        self.assertEqual(self.outbox.cursor(), 0)
        self.assertEqual(self.outbox.rows(), [])
        self.assertEqual(self.outbox.enqueue(), 1)

    def test_restart_recovers_inflight_same_event_id(self):
        row = self.queue()
        with self.outbox.connect() as db:
            db.execute("UPDATE outbox SET state='IN_FLIGHT'")
        again = m.SidecarOutbox(self.cfg, self.reader)
        self.assertEqual(again.rows()[0]['state'], 'PENDING')
        self.assertEqual(again.rows()[0]['event_id'], row['event_id'])

    def test_delivered_event_never_sent_again(self):
        self.queue()
        self.assertEqual(self.sender.send_due(), 1)
        self.assertEqual(self.sender.send_due(), 0)
        again = m.SidecarOutbox(self.cfg, self.reader)
        other = m.Sender(self.cfg, again, self.transport)
        self.assertEqual(other.send_due(), 0)
        self.assertEqual(len(self.transport.calls), 1)

    def test_retry_persisted_backoff_and_recovery(self):
        self.queue()
        self.transport.failure = m.DeliveryError('network_error')
        self.assertEqual(self.sender.send_due(), 0)
        row = self.outbox.rows()[0]
        self.assertEqual(row['state'], 'RETRY')
        self.assertGreater(row['next_attempt'], self.now)
        self.assertEqual(self.sender.send_due(), 0)
        self.assertEqual(len(self.transport.calls), 1)
        again = m.SidecarOutbox(self.cfg, self.reader)
        self.now = row['next_attempt'] + .01
        self.transport.failure = None
        self.assertEqual(m.Sender(self.cfg, again, self.transport, clock=lambda: self.now).send_due(), 1)

    def test_timeout_after_server_commit_retries_identical_body(self):
        self.queue()
        self.transport.failure = m.DeliveryError('network_error')
        self.sender.send_due()
        self.now += 20
        self.transport.failure = None
        self.transport.mutate = lambda ack: ack.update(replayed=True)
        self.assertEqual(self.sender.send_due(), 1)
        self.assertEqual(self.transport.calls[0][1], self.transport.calls[1][1])

    def test_exhausted_retained_explicit_requeue_only(self):
        row = self.queue()
        self.transport.failure = m.DeliveryError('network_error')
        for index in range(3):
            self.sender.send_due(); self.now += 100
        self.assertEqual(self.outbox.rows()[0]['state'], 'RETRY_EXHAUSTED')
        self.assertEqual(self.sender.send_due(), 0)
        self.assertEqual(self.outbox.retry_exhausted(), {'events': 1, 'media': 0})
        self.transport.failure = None
        self.assertEqual(self.sender.send_due(), 1)
        self.assertEqual(self.outbox.rows()[0]['event_id'], row['event_id'])
        self.assertEqual(self.outbox.retry_exhausted(), {'events': 0, 'media': 0})

    def test_auth_failure_blocks_batch_and_survives_restart(self):
        self.add(); self.add(); self.outbox.enqueue()
        self.transport.failure = m.DeliveryError('http_401', 401)
        self.sender.send_due()
        self.assertEqual(len(self.transport.calls), 1)
        self.assertTrue(m.Sender(self.cfg, self.outbox, self.transport).auth_blocked)
        self.assertEqual(self.outbox.retry_exhausted(), {'events': 0, 'media': 0})

    def test_validation_conflict_quarantined_without_retry(self):
        for status in (400, 404, 409, 410, 413, 415, 422):
            with self.subTest(status=status):
                self.add(); self.outbox.enqueue()
                self.transport.failure = m.DeliveryError('http_error', status)
                self.sender.send_due()
                self.assertEqual(self.outbox.rows()[-1]['state'], 'QUARANTINED')

    def test_ack_invalid_identity_origin_or_ids_not_accepted(self):
        self.queue()
        changes = [{'event_id': str(uuid.uuid4())}, {'producer_id': 'other'},
                   {'data_origin': 'REAL_AI'}, {'schema_version': '2'},
                   {'receipt_id': True}, {'replayed': 1}]
        for change in changes:
            with self.subTest(change=change):
                self.transport.mutate = lambda ack: ack.update(change)
                with self.outbox.connect() as db:
                    db.execute("UPDATE outbox SET state='PENDING',attempts=0,next_attempt=0")
                self.assertEqual(self.sender.send_due(), 0)
                self.assertNotEqual(self.outbox.rows()[0]['state'], 'DELIVERED')

    def test_missing_media_ack_still_acknowledges_persisted_event(self):
        self.queue()
        self.transport.mutate = lambda ack: ack.update(evidence_status='MISSING', replayed=True)
        self.assertEqual(self.sender.send_due(), 1)
        row = self.outbox.rows()[0]
        self.assertEqual(row['state'], 'DELIVERED')
        self.assertEqual(row['evidence_status'], 'MISSING')
        self.assertNotEqual(row['media_state'], 'DELIVERED')

    def test_tampered_outbox_payload_refused(self):
        self.queue()
        with self.outbox.connect() as db:
            db.execute("UPDATE outbox SET payload='{}'")
        with self.assertRaises(m.SafetyError):
            self.sender.send_due()
        self.assertEqual(self.transport.calls, [])

    def test_source_history_replacement_or_truncation_refused(self):
        self.queue()
        with connect(self.source) as db:
            db.execute("UPDATE events SET details_json='{}' WHERE id=1")
        with self.assertRaises(m.SafetyError):
            self.outbox.enqueue()

    def test_late_evidence_does_not_change_event_payload(self):
        row = self.queue()
        with connect(self.source) as db:
            db.execute('UPDATE events SET evidence_path=? WHERE id=1', (str(self.root / 'late.jpg'),))
        self.assertEqual(self.outbox.enqueue(), 0)
        self.assertEqual(self.outbox.rows()[0]['payload'], row['payload'])

    def test_outbox_cannot_change_origin_or_generation(self):
        self.queue()
        for key, value in [('data_origin', 'REAL_AI'), ('producer_instance_id', str(uuid.uuid4()))]:
            other = dict(self.cfg); other[key] = value
            with self.subTest(key=key), self.assertRaises(m.SafetyError):
                m.SidecarOutbox(other, self.reader)

    def test_bad_event_quarantined_cursor_moves_next_valid_event(self):
        self.add(kind='CAMERA_OFFLINE'); self.add(details={'object_contact_score': 1.1}); self.add()
        self.assertEqual(self.outbox.enqueue(), 3)
        self.assertEqual([r['state'] for r in self.outbox.rows()], ['QUARANTINED', 'QUARANTINED', 'PENDING'])
        self.assertEqual(self.outbox.cursor(), 3)
        self.assertEqual(self.sender.send_due(), 1)

    def test_payload_time_source_utc_and_raw_score(self):
        self.add(details={'alert_at': '2026-10-28T17:00:00+07:00', 'object_contact_score': .91})
        self.outbox.enqueue()
        p = json.loads(self.outbox.rows()[0]['payload'])
        self.assertEqual(p['detected_at'], '2026-10-28T10:00:00Z')
        self.assertEqual(p['time_source'], 'ALERT_DECISION')
        self.assertEqual(p['scores'], {'object_contact': .91})
        self.assertNotIn('confidence', p)

    def test_missing_aware_alert_time_uses_eventstore_utc(self):
        self.add(details={'alert_at': '2026-10-28T17:00:00'})
        self.outbox.enqueue()
        p = json.loads(self.outbox.rows()[0]['payload'])
        self.assertEqual(p['time_source'], 'EVENTSTORE_RECORD')
        self.assertTrue(p['detected_at'].endswith('Z'))

    def test_config_rejects_unsafe_path_origin_and_targets(self):
        variations = [{'source_db': str(self.root / 'missing')}, {'outbox_db': str(self.source)},
                      {'backend_url': 'http://172.20.10.3'}, {'profile': 'PRODUCTION'},
                      {'data_origin': 'REAL_AI'}, {'producer_id': 'x' * 81},
                      {'max_attempts': 0}, {'outbox_db': str(self.root.parent / 'escape.sqlite')}]
        for change in variations:
            with self.subTest(change=change), self.assertRaises((m.SafetyError, ValueError)):
                m.validate_config(dict(self.cfg, **change))

    def test_media_pending_then_late_jpeg_uploaded(self):
        self.queue(); self.sender.send_due()
        self.assertEqual(self.sender.send_media(), 0)
        path = self.root / 'test_SYNTHETIC_TEST.jpg'; path.write_bytes(b'\xff\xd8\xffTEST\xff\xd9')
        with connect(self.source) as db:
            db.execute('UPDATE events SET evidence_path=? WHERE id=1', (str(path),))
        self.assertEqual(self.sender.send_media(), 1)
        self.assertEqual(self.outbox.rows()[0]['media_state'], 'DELIVERED')
        self.assertEqual(self.sender.send_media(), 0)
        self.assertEqual(self.transport.calls[-1][3]['X-Evidence-SHA256'], m.sha(path.read_bytes()))

    def test_media_ack_wrong_provenance_not_accepted(self):
        self.queue(); self.sender.send_due()
        path = self.root / 'test_SYNTHETIC_TEST.jpg'; path.write_bytes(b'\xff\xd8\xffTEST\xff\xd9')
        with connect(self.source) as db:
            db.execute('UPDATE events SET evidence_path=? WHERE id=1', (str(path),))
        self.transport.mutate = lambda ack: ack.update(data_origin='REAL_AI')
        self.assertEqual(self.sender.send_media(), 0)
        self.assertEqual(self.outbox.rows()[0]['media_state'], 'PENDING')

    def test_media_path_traversal_quarantined_without_http(self):
        self.queue(); self.sender.send_due()
        with connect(self.source) as db:
            db.execute('UPDATE events SET evidence_path=? WHERE id=1', (str(self.root.parent / 'outside.jpg'),))
        self.assertEqual(self.sender.send_media(), 0)
        self.assertEqual(self.outbox.rows()[0]['media_state'], 'QUARANTINED')
        self.assertEqual(len(self.transport.calls), 1)

    def test_transport_rejects_target_redirect_and_unsafe_path(self):
        with self.assertRaises(m.SafetyError):
            m.HttpTransport('http://example.com', 'private-test-key')
        transport = m.HttpTransport(m.BACKEND, 'private-test-key')
        with self.assertRaises(m.SafetyError):
            transport.request('/api/../escape', b'{}', 'application/json')
        with self.assertRaises(m.DeliveryError):
            m.NoRedirect().redirect_request(None)


if __name__ == '__main__':
    unittest.main()
