"""SYNTHETIC_TEST HTTP contract via in-process ASGI, SQLite memory only."""
from pathlib import Path
import hashlib
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "full_integration"))
from test_support import IsolatedBackend

class HttpTests(unittest.TestCase):
    def setUp(self):
        self.fx = IsolatedBackend(http=True)
        self.client = self.fx.client

    def tearDown(self):
        self.fx.close()

    def post(self, payload=None, headers=None):
        return self.client.post("/api/v1/ai/events", json=payload or self.fx.event_dict(),
                                headers=self.fx.producer_headers if headers is None else headers)

    def test_create_persist_query_origin(self):
        payload = self.fx.event_dict()
        response = self.post(payload)
        self.assertEqual(response.status_code, 201, response.text)
        ack = response.json()
        self.assertEqual(ack["event_id"], payload["event_id"])
        self.assertEqual(ack["data_origin"], "SYNTHETIC_TEST")
        alerts = self.client.get("/api/v1/alerts", headers=self.fx.human_headers)
        self.assertEqual(alerts.status_code, 200, alerts.text)
        self.assertEqual(alerts.json()["items"][0]["id"], ack["alert_id"])
        origins = self.client.get("/api/v1/ai/alert-origins", params={"alert_ids": str(ack["alert_id"])},
                                  headers=self.fx.human_headers)
        self.assertEqual(origins.status_code, 200, origins.text)
        self.assertEqual(origins.json()["items"][0]["event_id"], payload["event_id"])

    def test_exact_replay_idempotent(self):
        payload = self.fx.event_dict()
        first = self.post(payload)
        before = self.fx.counts()
        second = self.post(payload)
        self.assertEqual((first.status_code, second.status_code), (201, 200))
        self.assertTrue(second.json()["replayed"])
        self.assertEqual(first.json()["alert_id"], second.json()["alert_id"])
        self.assertEqual(self.fx.counts(), before)

    def test_changed_payload_conflict(self):
        payload = self.fx.event_dict()
        self.post(payload)
        before = self.fx.counts()
        payload["scores"]["object_contact"] = 0.95
        self.assertEqual(self.post(payload).status_code, 409)
        self.assertEqual(self.fx.counts(), before)

    def test_missing_producer_key(self):
        self.assertEqual(self.post(headers={}).status_code, 401)
        self.assertEqual(self.fx.counts(), (0,) * 8)

    def test_invalid_producer_key(self):
        self.assertEqual(self.post(headers={"X-ArtGuard-Producer-Key": "invalid"}).status_code, 401)

    def test_human_jwt_cannot_ingest(self):
        self.assertEqual(self.post(headers=self.fx.human_headers).status_code, 401)

    def test_producer_key_cannot_query_human_data(self):
        self.assertEqual(self.client.get("/api/v1/alerts", headers=self.fx.producer_headers).status_code, 401)

    def test_origin_scope_rejects_real_ai(self):
        self.assertEqual(self.post(self.fx.event_dict(data_origin="REAL_AI")).status_code, 403)
        self.assertEqual(self.fx.counts(), (0,) * 8)

    def test_unknown_identity_and_instance(self):
        for changes in ({"producer_id": "other"}, {"producer_instance_id": str(uuid4())}):
            with self.subTest(changes=changes):
                self.assertEqual(self.post(self.fx.event_dict(**changes)).status_code, 403)

    def test_invalid_fields_rejected_without_write(self):
        for changes in ({"schema_version": "2"}, {"event_id": "bad"},
                        {"data_origin": "DEMO"}, {"detected_at": "2026-01-01T12:00:00"},
                        {"scores": {"object_contact": True}}, {"device_id": True},
                        {"evidence_path": "../secret"}):
            with self.subTest(changes=changes):
                self.assertEqual(self.post(self.fx.event_dict(**changes)).status_code, 422)
        self.assertEqual(self.fx.counts(), (0,) * 8)

    def test_invalid_json_rejected(self):
        response = self.client.post("/api/v1/ai/events", content=b"{",
                headers={**self.fx.producer_headers, "Content-Type": "application/json"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.fx.counts(), (0,) * 8)

    def test_invalid_content_length_rejected_cleanly(self):
        response = self.post(headers={**self.fx.producer_headers, "Content-Length": "invalid"})
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.fx.counts(), (0,) * 8)

    def test_oversized_metadata_rejected(self):
        response = self.post(headers={**self.fx.producer_headers, "Content-Length": "70000"})
        self.assertEqual(response.status_code, 413)
        self.assertEqual(self.fx.counts(), (0,) * 8)

    def test_missing_db_mapping_rejected_without_partial(self):
        from dataclasses import replace
        missing = replace(self.fx.producer, artwork_id=999, device_id=None)
        self.fx.app.state.integration_config = replace(self.fx.config, producers=(missing,))
        self.assertEqual(self.post(self.fx.event_dict(artwork_id=999, device_id=None)).status_code, 422)
        self.assertEqual(self.fx.counts(), (0,) * 8)

    def test_failure_rolls_back_all_business_rows(self):
        from app.services import ai_event_ingest
        with patch.object(ai_event_ingest, "record_audit", side_effect=RuntimeError("test failure")):
            self.assertEqual(self.post().status_code, 500)
        self.assertEqual(self.fx.counts(), (0,) * 8)

    def media(self, event_id, data, **headers):
        return self.client.put("/api/v1/ai/events/" + event_id + "/evidence", content=data,
                headers={**self.fx.producer_headers, "Content-Type": "image/jpeg",
                         "X-Evidence-SHA256": hashlib.sha256(data).hexdigest(), **headers})

    def test_evidence_create_replay_secure_get(self):
        ack = self.post().json()
        data = self.fx.jpeg()
        response = self.media(ack["event_id"], data)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["data_origin"], "SYNTHETIC_TEST")
        self.assertEqual(self.media(ack["event_id"], data).status_code, 200)
        url = "/api/v1/evidence-media/" + str(response.json()["media_id"]) + "/file"
        self.assertEqual(self.client.get(url).status_code, 401)
        viewed = self.client.get(url, headers=self.fx.human_headers)
        self.assertEqual(viewed.status_code, 200, viewed.text[:80])
        self.assertEqual(viewed.content, data)

    def test_evidence_unknown_event(self):
        self.assertEqual(self.media(str(uuid4()), self.fx.jpeg()).status_code, 404)

    def test_evidence_digest_mismatch(self):
        ack = self.post().json()
        self.assertEqual(self.media(ack["event_id"], self.fx.jpeg(),
                                  **{"X-Evidence-SHA256": "a"*64}).status_code, 422)
        self.assertEqual(self.fx.counts()[-2:], (0, 0))

    def test_evidence_wrong_mime_and_invalid_jpeg(self):
        ack = self.post().json()
        self.assertEqual(self.media(ack["event_id"], self.fx.jpeg(),
                                  **{"Content-Type": "application/octet-stream"}).status_code, 415)
        self.assertEqual(self.media(ack["event_id"], b"bad").status_code, 415)
        self.assertEqual(self.fx.counts()[-2:], (0, 0))

    def test_evidence_size_bounded(self):
        ack = self.post().json()
        self.assertEqual(self.media(ack["event_id"], b"x" * (5*1024*1024+1)).status_code, 413)
        self.assertEqual(self.fx.counts()[-2:], (0, 0))

    def test_evidence_payload_conflict(self):
        ack = self.post().json()
        self.assertEqual(self.media(ack["event_id"], self.fx.jpeg("white")).status_code, 201)
        before = self.fx.counts()
        self.assertEqual(self.media(ack["event_id"], self.fx.jpeg("black")).status_code, 409)
        self.assertEqual(self.fx.counts(), before)

    def test_origin_query_requires_human_and_valid_ids(self):
        self.assertEqual(self.client.get("/api/v1/ai/alert-origins?alert_ids=1").status_code, 401)
        for ids in ("", "0", "-1", "1,no", ",".join(["1"]*101)):
            with self.subTest(ids=ids[:30]):
                self.assertEqual(self.client.get("/api/v1/ai/alert-origins", params={"alert_ids": ids},
                                                  headers=self.fx.human_headers).status_code, 422)

    def test_test_status_and_health(self):
        self.assertEqual(self.client.get("/api/v1/ai/status").status_code, 401)
        status = self.client.get("/api/v1/ai/status", headers=self.fx.human_headers)
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["data_mode"], "integration_test")
        self.assertEqual(self.client.get("/health").json()["database"], ":memory:")

    def test_equivalent_timezone_replay(self):
        payload = self.fx.event_dict()
        self.assertEqual(self.post(payload).status_code, 201)
        payload["detected_at"] = "2026-10-27T17:00:00+07:00"
        self.assertEqual(self.post(payload).status_code, 200)

    def test_real_ai_only_under_real_scope(self):
        from dataclasses import replace
        real = replace(self.fx.producer, allowed_origins=("REAL_AI",))
        self.fx.app.state.integration_config = replace(self.fx.config, producers=(real,))
        response = self.post(self.fx.event_dict(data_origin="REAL_AI"))
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["data_origin"], "REAL_AI")
        with self.fx.factory() as db:
            evidence = db.get(self.fx.models.Evidence, response.json()["evidence_id"])
            self.assertEqual(evidence.source, "ai")
            self.assertIsNone(evidence.confidence)


    def test_chunked_metadata_limit_before_json_parse(self):
        import json
        payload = json.dumps(self.fx.event_dict()).encode()
        def chunks():
            yield payload
            yield b" " * 66000
        response = self.client.post("/api/v1/ai/events", content=chunks(),
                headers={**self.fx.producer_headers, "Content-Type": "application/json"})
        self.assertEqual(response.status_code, 413, response.text)
        self.assertEqual(self.fx.counts(), (0,) * 8)

    def test_chunked_valid_metadata_preserves_payload(self):
        import json
        payload = self.fx.event_dict()
        encoded = json.dumps(payload).encode()
        def chunks():
            yield encoded[:70]
            yield encoded[70:]
        response = self.client.post("/api/v1/ai/events", content=chunks(),
                headers={**self.fx.producer_headers, "Content-Type": "application/json"})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["event_id"], payload["event_id"])

if __name__ == "__main__":
    unittest.main(verbosity=2)
