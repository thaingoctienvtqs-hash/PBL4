"""TEST-only, standard-library EventStore reader/outbox/sender. Python 3.7+.
No model, camera, network or database work occurs on import.
"""
import argparse
import hashlib
import json
import math
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

REPO = Path(__file__).resolve().parents[2]
BACKEND = "http://127.0.0.1:8101"
MAX_JPEG = 5 * 1024 * 1024
EVENT_TYPE = "AI_CONTACT_SUSPECTED_IN_ROI"


class SafetyError(ValueError):
    pass


class DeliveryError(RuntimeError):
    def __init__(self, code, status=None):
        super().__init__(code)
        self.code, self.status = code, status


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def inside(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except (ValueError, OSError):
        return False


def controlled_path(path, root, must_exist=False):
    value = Path(path).expanduser().resolve()
    if not inside(value, root):
        raise SafetyError("path_outside_test_root")
    if must_exist and not value.is_file():
        raise SafetyError("source_file_missing")
    return value


def utc_stamp(value):
    if not isinstance(value, str):
        raise ValueError("timestamp_not_string")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp_not_aware")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_config(value):
    cfg = dict(value)
    root = Path(cfg["test_root"]).expanduser().resolve()
    if not root.is_dir() or inside(root, REPO) or inside(REPO, root):
        raise SafetyError("test_root_must_be_existing_external_directory")
    if cfg.get("profile") != "TEST":
        raise SafetyError("test_profile_required")
    if str(cfg.get("backend_url", "")).rstrip("/") != BACKEND:
        raise SafetyError("backend_target_not_allowlisted")
    cfg["test_root"] = str(root)
    source = controlled_path(cfg["source_db"], root, True)
    outbox = controlled_path(cfg["outbox_db"], root)
    if source == outbox:
        raise SafetyError("source_and_outbox_must_differ")
    cfg.update(source_db=str(source), outbox_db=str(outbox))
    cfg["evidence_root"] = str(controlled_path(cfg.get("evidence_root", root), root))
    producer = cfg.get("producer_id")
    if not isinstance(producer, str) or not producer or len(producer) > 100:
        raise SafetyError("invalid_producer_id")
    cfg["producer_instance_id"] = str(uuid.UUID(str(cfg["producer_instance_id"])))
    if cfg.get("data_origin") not in ("SYNTHETIC_TEST", "REAL_AI"):
        raise SafetyError("unknown_origin")
    if cfg["data_origin"] == "REAL_AI":
        required = ("new_test_session", "camera_source_confirmed", "roi_confirmed", "real_ai_authorized")
        if not all(cfg.get(k) is True for k in required):
            raise SafetyError("real_ai_provenance_not_confirmed")
    cfg["source_start_id"] = int(cfg.get("source_start_id", 0))
    if cfg["source_start_id"] < 0:
        raise SafetyError("invalid_start_id")
    cfg["max_attempts"] = int(cfg.get("max_attempts", 5))
    if not 1 <= cfg["max_attempts"] <= 10:
        raise SafetyError("invalid_attempt_limit")
    cfg["retry_base_seconds"] = float(cfg.get("retry_base_seconds", 1.0))
    cfg["retry_cap_seconds"] = float(cfg.get("retry_cap_seconds", 30.0))
    if not 0 < cfg["retry_base_seconds"] <= cfg["retry_cap_seconds"] <= 300:
        raise SafetyError("invalid_retry_policy")
    return cfg


class ReadOnlyEventReader:
    def __init__(self, source):
        self.path = Path(source).resolve()
        if not self.path.is_file():
            raise SafetyError("source_file_missing")
        with self.connect() as db:
            cols = {r[1] for r in db.execute("PRAGMA table_info(events)")}
            required = {"id", "timestamp", "kind", "status", "details_json", "evidence_path"}
            if not required.issubset(cols):
                raise SafetyError("eventstore_schema_mismatch")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=2.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        try:
            yield db
        finally:
            db.close()

    def after(self, cursor, limit=100):
        if not 1 <= int(limit) <= 1000:
            raise ValueError("invalid_batch_limit")
        with self.connect() as db:
            rows = db.execute(
                "SELECT id,timestamp,kind,status,details_json,evidence_path FROM events "
                "WHERE id>? ORDER BY id ASC LIMIT ?", (int(cursor), int(limit))).fetchall()
        return [dict(r) for r in rows]

    def get(self, ident):
        with self.connect() as db:
            row = db.execute("SELECT id,timestamp,kind,status,details_json,evidence_path FROM events WHERE id=?",
                             (int(ident),)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def anchor(row):
        # evidence_path is intentionally excluded: v3 fills it after event commit.
        return sha(canonical({k: row[k] for k in
                              ("id", "timestamp", "kind", "status", "details_json")}).encode("utf8"))


def build_payload(row, cfg):
    details = json.loads(row["details_json"])
    if not isinstance(details, dict) or row["kind"] != EVENT_TYPE:
        raise ValueError("unsupported_event")
    score = details.get("object_contact_score")
    scores = {}
    if score is not None:
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("invalid_object_contact_score")
        scores["object_contact"] = float(score)
    try:
        detected = utc_stamp(details["alert_at"])
        time_source = "ALERT_DECISION"
    except (KeyError, ValueError, TypeError):
        timestamp = float(row["timestamp"])
        if not math.isfinite(timestamp):
            raise ValueError("invalid_event_timestamp")
        detected = datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")
        time_source = "EVENTSTORE_RECORD"
    event_id = str(uuid.uuid5(uuid.UUID(cfg["producer_instance_id"]),
                              cfg["producer_id"] + ":" + str(row["id"])))
    return {
        "schema_version": "1", "event_id": event_id,
        "producer_id": cfg["producer_id"], "producer_instance_id": cfg["producer_instance_id"],
        "source_event_id": str(row["id"]), "data_origin": cfg["data_origin"],
        "event_type": EVENT_TYPE, "detected_at": detected, "time_source": time_source,
        "artwork_id": cfg.get("artwork_id"), "device_id": cfg.get("device_id"),
        "scores": scores, "evidence_ref": {"status": "PENDING"},
    }


class SidecarOutbox:
    def __init__(self, cfg, reader):
        self.cfg, self.reader = cfg, reader
        self.path = Path(cfg["outbox_db"])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS outbox(event_id TEXT PRIMARY KEY,source_id INTEGER UNIQUE NOT NULL,"
                "payload TEXT,payload_sha TEXT,source_anchor TEXT NOT NULL,state TEXT NOT NULL,"
                "attempts INTEGER NOT NULL DEFAULT 0,next_attempt REAL NOT NULL DEFAULT 0,error_code TEXT,"
                "receipt_id INTEGER,alert_id INTEGER,evidence_id INTEGER,evidence_status TEXT,"
                "media_state TEXT NOT NULL DEFAULT 'PENDING',media_sha TEXT,media_attempts INTEGER NOT NULL DEFAULT 0,"
                "media_next_attempt REAL NOT NULL DEFAULT 0)")
            identity = canonical({k: cfg[k] for k in ("producer_id", "producer_instance_id", "source_db", "data_origin")})
            old = db.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()
            if old and old[0] != identity:
                raise SafetyError("outbox_identity_conflict")
            db.execute("INSERT OR IGNORE INTO metadata(key,value) VALUES('identity',?)", (identity,))
            db.execute("INSERT OR IGNORE INTO metadata(key,value) VALUES('cursor',?)", (str(cfg["source_start_id"]),))
            # A prior process may have died after sending but before recording its ACK.
            db.execute("UPDATE outbox SET state='PENDING' WHERE state='IN_FLIGHT'")
        self.verify_anchor()

    @contextmanager
    def connect(self):
        db = sqlite3.connect(str(self.path), timeout=3.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA temp_store=MEMORY")
        try:
            with db:
                yield db
        finally:
            db.close()

    def cursor(self):
        with self.connect() as db:
            return int(db.execute("SELECT value FROM metadata WHERE key='cursor'").fetchone()[0])

    def verify_anchor(self):
        with self.connect() as db:
            row = db.execute("SELECT source_id,source_anchor FROM outbox ORDER BY source_id DESC LIMIT 1").fetchone()
        if row:
            original = self.reader.get(row["source_id"])
            if original is None or self.reader.anchor(original) != row["source_anchor"]:
                raise SafetyError("source_generation_or_history_changed")

    def enqueue(self, limit=100, before_commit=None):
        self.verify_anchor()
        rows = self.reader.after(self.cursor(), limit)
        count = 0
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for row in rows:
                try:
                    payload = build_payload(row, self.cfg)
                    text = canonical(payload)
                    event_id, state, error = payload["event_id"], "PENDING", None
                    digest = sha(text.encode("utf8"))
                except (ValueError, TypeError, OverflowError, OSError) as exc:
                    text, digest = None, None
                    event_id = str(uuid.uuid5(uuid.UUID(self.cfg["producer_instance_id"]),
                                             self.cfg["producer_id"] + ":" + str(row["id"])))
                    state, error = "QUARANTINED", type(exc).__name__
                db.execute(
                    "INSERT OR IGNORE INTO outbox(event_id,source_id,payload,payload_sha,source_anchor,state,error_code) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (event_id, row["id"], text, digest, self.reader.anchor(row), state, error))
                db.execute("UPDATE metadata SET value=? WHERE key='cursor'", (str(row["id"]),))
                count += 1
            if before_commit:
                before_commit()
        return count

    def rows(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM outbox ORDER BY source_id")]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise DeliveryError("redirect_refused")


class HttpTransport:
    def __init__(self, base_url, key, timeout=5.0):
        if str(base_url).rstrip("/") != BACKEND:
            raise SafetyError("backend_target_not_allowlisted")
        if not key:
            raise SafetyError("producer_key_missing")
        if not 0 < float(timeout) <= 30:
            raise SafetyError("invalid_http_timeout")
        self.base, self.key, self.timeout = BACKEND, key, float(timeout)
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, path, body, content_type, extra_headers=None):
        if not path.startswith("/api/v1/ai/events") or "?" in path or ".." in path:
            raise SafetyError("unexpected_ingest_path")
        headers = {"X-ArtGuard-Producer-Key": self.key, "Content-Type": content_type,
                   "Connection": "close", "User-Agent": "ArtGuard-TEST-Sender/1"}
        headers.update(extra_headers or {})
        request = Request(self.base + path, data=body, headers=headers,
                          method="PUT" if path.endswith("/evidence") else "POST")
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                if response.status not in (200, 201):
                    raise DeliveryError("unexpected_http_status", response.status)
                data = response.read(1024 * 1024 + 1)
                if len(data) > 1024 * 1024:
                    raise DeliveryError("ack_too_large")
                return response.status, json.loads(data.decode("utf8"))
        except HTTPError as exc:
            raise DeliveryError("http_{}".format(exc.code), exc.code)
        except DeliveryError:
            raise
        except (URLError, TimeoutError, OSError):
            raise DeliveryError("network_error")
        except (ValueError, UnicodeError):
            raise DeliveryError("invalid_ack_json")


class Sender:
    def __init__(self, cfg, outbox, transport, clock=time.time):
        self.cfg, self.outbox, self.transport, self.clock = cfg, outbox, transport, clock
        self.auth_blocked = any(r["state"] == "AUTH_BLOCKED" or r["media_state"] == "AUTH_BLOCKED"
                                for r in outbox.rows())

    def _validate_ack(self, ack, row, media=False):
        payload = json.loads(row["payload"])
        if not isinstance(ack, dict) or ack.get("event_id") != row["event_id"] or ack.get("producer_id") != self.cfg["producer_id"]:
            raise DeliveryError("ack_identity_mismatch")
        for key in ("receipt_id", "alert_id", "evidence_id"):
            if isinstance(ack.get(key), bool) or not isinstance(ack.get(key), int) or ack[key] <= 0:
                raise DeliveryError("invalid_ack_ids")
        if not isinstance(ack.get("replayed"), bool):
            raise DeliveryError("invalid_replay_ack")
        if media:
            if any(row[k] is not None and ack[k] != row[k] for k in ("receipt_id", "alert_id", "evidence_id")):
                raise DeliveryError("media_ack_ids_changed")
            if not isinstance(ack.get("media_id"), int) or isinstance(ack.get("media_id"), bool) or ack["media_id"] <= 0:
                raise DeliveryError("invalid_media_id")
            if ack.get("evidence_status") != "READY":
                raise DeliveryError("invalid_media_ack")
        elif ack.get("schema_version") != "1" or ack.get("data_origin") != payload["data_origin"] or ack.get("evidence_status") not in ("PENDING", "READY"):
            raise DeliveryError("invalid_ack_origin_or_version")

    def send_due(self, limit=100):
        if self.auth_blocked:
            return 0
        now, sent = self.clock(), 0
        with self.outbox.connect() as db:
            rows = [dict(r) for r in db.execute(
                "SELECT * FROM outbox WHERE state IN ('PENDING','RETRY') AND next_attempt<=? "
                "ORDER BY source_id LIMIT ?", (now, int(limit)))]
        for row in rows:
            if sha(row["payload"].encode("utf8")) != row["payload_sha"]:
                raise SafetyError("outbox_payload_changed")
            attempts = row["attempts"] + 1
            with self.outbox.connect() as db:
                db.execute("UPDATE outbox SET state='IN_FLIGHT',attempts=? WHERE event_id=?",
                           (attempts, row["event_id"]))
            try:
                _, ack = self.transport.request("/api/v1/ai/events", row["payload"].encode("utf8"), "application/json")
                self._validate_ack(ack, row)
                with self.outbox.connect() as db:
                    db.execute(
                        "UPDATE outbox SET state='DELIVERED',error_code=NULL,receipt_id=?,alert_id=?,evidence_id=?,"
                        "evidence_status=? WHERE event_id=?",
                        (ack["receipt_id"], ack["alert_id"], ack["evidence_id"], ack.get("evidence_status", "PENDING"), row["event_id"]))
                sent += 1
            except DeliveryError as exc:
                status = exc.status
                if status in (401, 403):
                    state = "AUTH_BLOCKED"
                    self.auth_blocked = True
                elif status in (400, 404, 409, 422):
                    state = "QUARANTINED"
                elif attempts >= self.cfg["max_attempts"]:
                    state = "RETRY_EXHAUSTED"
                else:
                    state = "RETRY"
                delay = min(self.cfg["retry_cap_seconds"], self.cfg["retry_base_seconds"] * (2 ** (attempts - 1)))
                # Stable bounded jitter: reproducible across restart, no random dependency.
                delay *= .9 + (int(row["event_id"].replace("-", "")[-2:], 16) / 255.) * .2
                with self.outbox.connect() as db:
                    db.execute("UPDATE outbox SET state=?,next_attempt=?,error_code=? WHERE event_id=?",
                               (state, now + delay, exc.code, row["event_id"]))
                if self.auth_blocked:
                    break
        return sent

    def send_media(self, limit=100):
        if self.auth_blocked:
            return 0
        sent = 0
        rows = [r for r in self.outbox.rows() if r["state"] == "DELIVERED" and r["media_state"] == "PENDING"
                and r["media_next_attempt"] <= self.clock()]
        for row in rows[:int(limit)]:
            original = self.outbox.reader.get(row["source_id"])
            if not original or not original["evidence_path"]:
                continue
            attempts = row["media_attempts"] + 1
            try:
                path = controlled_path(original["evidence_path"], self.cfg["evidence_root"], True)
                if path.stat().st_size > MAX_JPEG:
                    raise SafetyError("evidence_too_large")
                data = path.read_bytes()
                if not data.startswith(b"\xff\xd8\xff") or not data.rstrip().endswith(b"\xff\xd9"):
                    raise SafetyError("evidence_not_jpeg")
                digest = sha(data)
                if row["media_sha"] and row["media_sha"] != digest:
                    raise SafetyError("evidence_changed_after_first_send")
                with self.outbox.connect() as db:
                    db.execute("UPDATE outbox SET media_sha=?,media_attempts=? WHERE event_id=?",
                               (digest, attempts, row["event_id"]))
                _, ack = self.transport.request("/api/v1/ai/events/" + row["event_id"] + "/evidence",
                                                data, "image/jpeg", {"X-Evidence-SHA256": digest})
                self._validate_ack(ack, row, media=True)
                with self.outbox.connect() as db:
                    db.execute("UPDATE outbox SET media_state='DELIVERED',evidence_status='READY' WHERE event_id=?",
                               (row["event_id"],))
                sent += 1
            except SafetyError as exc:
                with self.outbox.connect() as db:
                    db.execute("UPDATE outbox SET media_state='QUARANTINED',error_code=? WHERE event_id=?",
                               (str(exc), row["event_id"]))
            except DeliveryError as exc:
                state = "AUTH_BLOCKED" if exc.status in (401, 403) else (
                    "QUARANTINED" if exc.status in (400, 404, 409, 422) else (
                    "RETRY_EXHAUSTED" if attempts >= self.cfg["max_attempts"] else "PENDING"))
                with self.outbox.connect() as db:
                    db.execute("UPDATE outbox SET media_state=?,media_attempts=?,media_next_attempt=?,error_code=? WHERE event_id=?",
                               (state, attempts, self.clock() + min(self.cfg["retry_cap_seconds"], self.cfg["retry_base_seconds"] * (2 ** (attempts - 1))), exc.code, row["event_id"]))
                if state == "AUTH_BLOCKED":
                    self.auth_blocked = True
                    break
        return sent


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--send", action="store_true", help="explicit opt-in to loopback TEST backend HTTP")
    parser.add_argument("--max-batches", type=int, default=1)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--key-env", default="ARTGUARD_AI_PRODUCER_KEY")
    args = parser.parse_args(argv)
    if not 1 <= args.max_batches <= 1000 or not .1 <= args.poll_seconds <= 60:
        parser.error("bounded batches/poll interval required")
    cfg = validate_config(json.loads(Path(args.config).read_text(encoding="utf8")))
    reader = ReadOnlyEventReader(cfg["source_db"])
    outbox = SidecarOutbox(cfg, reader)
    sender = Sender(cfg, outbox, HttpTransport(cfg["backend_url"], os.environ.get(args.key_env, ""))) if args.send else None
    for index in range(args.max_batches):
        queued = outbox.enqueue()
        delivered = sender.send_due() if sender else 0
        media = sender.send_media() if sender else 0
        print(canonical({"batch": index + 1, "queued": queued, "delivered": delivered, "media": media,
                         "states": [r["state"] for r in outbox.rows()]}), flush=True)
        if sender and sender.auth_blocked:
            return 2
        if index + 1 < args.max_batches:
            time.sleep(args.poll_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
