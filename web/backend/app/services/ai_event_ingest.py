"""Atomic receipt/Alert/Evidence ingest and separately idempotent JPEG attachment."""
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import hashlib
import json
import re
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.ai_event_models import AiEventAttachment, AiEventReceipt
from app.ai_event_schemas import AiEventAck, AiEventIn, MediaAck
from app.audit import record_audit
from app.models import Alert, AlertHistory, Artwork, Device, Evidence, EvidenceHistory, EvidenceMedia

MAX_MEDIA_BYTES = 5 * 1024 * 1024

def now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)

def canonical_event(event: AiEventIn):
    value = json.dumps(event.model_dump(mode="json"), sort_keys=True,
                       separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return value, hashlib.sha256(value.encode("utf-8")).hexdigest()

def authorize_event(event, producer):
    if event.producer_id != producer.producer_id or event.data_origin not in producer.allowed_origins:
        raise HTTPException(403, "Producer identity or origin scope mismatch")
    if producer.producer_instance_id is not None and str(event.producer_instance_id) != producer.producer_instance_id:
        raise HTTPException(403, "Producer instance is not authorized")
    if event.artwork_id != producer.artwork_id or event.device_id != producer.device_id:
        raise HTTPException(403, "Producer artwork/device mapping is not authorized")

def find_receipt(db, producer_id, event_id):
    return db.scalar(select(AiEventReceipt).where(
        AiEventReceipt.producer_id == producer_id, AiEventReceipt.event_id == str(event_id)))

def _safe_media_path(config, relative):
    target = (config.media_root / relative).resolve()
    if not target.is_relative_to(config.media_root.resolve()):
        raise HTTPException(500, "Stored media reference is outside the controlled root")
    return target

def evidence_status(db, receipt, config):
    attachment = db.get(AiEventAttachment, receipt.id)
    if attachment is None:
        return "PENDING"
    media = db.get(EvidenceMedia, attachment.media_id) if attachment.media_id else None
    if media is None or not _safe_media_path(config, media.file_path).is_file():
        return "MISSING"
    return "READY"

def acknowledgment(db, receipt, config, replayed):
    if receipt.alert_id is None or receipt.evidence_id is None:
        raise HTTPException(500, "Incomplete ingest receipt")
    return AiEventAck(
        event_id=receipt.event_id, producer_id=receipt.producer_id,
        receipt_id=receipt.id, alert_id=receipt.alert_id, evidence_id=receipt.evidence_id,
        data_origin=receipt.data_origin, replayed=replayed,
        evidence_status=evidence_status(db, receipt, config))

def _unique_receipt_error(error):
    text = str(error.orig).lower()
    return ("uq_ai_event_producer_event" in text or
            "ai_event_receipts.producer_id, ai_event_receipts.event_id" in text)

def _unique_attachment_error(error):
    text = str(error.orig).lower()
    return ("ai_event_attachments.receipt_id" in text or
            ("duplicate key" in text and "ai_event_attachments" in text))

def ingest_event(db, event, producer, config):
    authorize_event(event, producer)
    canonical, digest = canonical_event(event)
    existing = find_receipt(db, producer.producer_id, event.event_id)
    if existing is not None:
        if existing.payload_sha256 != digest:
            raise HTTPException(409, "Event ID was already used with a different payload")
        return acknowledgment(db, existing, config, True), False
    try:
        if event.artwork_id is not None and db.get(Artwork, event.artwork_id) is None:
            raise HTTPException(422, "Unknown artwork")
        if event.device_id is not None:
            device = db.get(Device, event.device_id)
            if device is None:
                raise HTTPException(422, "Unknown device")
            if event.artwork_id is not None and device.artwork_id not in (None, event.artwork_id):
                raise HTTPException(422, "Device is mapped to a different artwork")
        stamp = now_utc()
        detected = event.detected_at.astimezone(timezone.utc).replace(tzinfo=None)
        receipt = AiEventReceipt(
            producer_id=producer.producer_id, event_id=str(event.event_id),
            producer_instance_id=str(event.producer_instance_id),
            source_event_id=event.source_event_id, schema_version=event.schema_version,
            data_origin=event.data_origin, event_type=event.event_type,
            detected_at=detected, received_at=stamp,
            payload_sha256=digest, payload_json=canonical)
        db.add(receipt)
        # Unique claim serializes concurrent requests before business rows exist.
        db.flush()
        source = "ai" if event.data_origin == "REAL_AI" else "synthetic_test"
        title = ("AI contact suspicion" if source == "ai" else "SYNTHETIC_TEST integration event")
        description = (
            "ContactHands Object-Contact suspicion after ROI/temporal confirmation; "
            "physical contact requires human verification."
            if source == "ai" else "Explicit synthetic event; not a camera/model detection.")
        alert = Alert(
            event_code="AIE-" + str(receipt.id), title=title, description=description,
            severity="medium", status="new", source=source, detected_at=detected,
            artwork_id=event.artwork_id, device_id=event.device_id)
        db.add(alert)
        db.flush()
        evidence = Evidence(
            evidence_code="AIEV-" + str(receipt.id), alert_id=alert.id,
            artwork_id=event.artwork_id, device_id=event.device_id,
            event_type=event.event_type, severity="medium", processing_status="pending",
            source=source, confidence=None, description=description,
            detected_at=detected, created_at=stamp, updated_at=stamp)
        db.add(evidence)
        db.flush()
        receipt.alert_id, receipt.evidence_id = alert.id, evidence.id
        db.add(AlertHistory(
            alert_id=alert.id, user_id=None, to_status="new", changed_at=stamp,
            note="Producer " + producer.producer_id + "; " + event.data_origin))
        db.add(EvidenceHistory(
            evidence_id=evidence.id, user_id=None, to_status="pending", changed_at=stamp,
            note="AI ingest metadata; evidence attachment pending"))
        record_audit(db, None, "ingest_ai_event", "alert", alert.id,
                     "producer=" + producer.producer_id + ";origin=" + event.data_origin)
        db.flush()
        response = acknowledgment(db, receipt, config, False)
        db.commit()
        return response, True
    except IntegrityError as error:
        db.rollback()
        if not _unique_receipt_error(error):
            raise
        existing = find_receipt(db, producer.producer_id, event.event_id)
        if existing is None:
            raise
        if existing.payload_sha256 != digest:
            raise HTTPException(409, "Event ID was already used with a different payload") from error
        return acknowledgment(db, existing, config, True), False
    except Exception:
        db.rollback()
        raise

def _media_ack(db, receipt, attachment, config, replayed):
    if evidence_status(db, receipt, config) != "READY":
        raise HTTPException(410, "Previously attached evidence is missing; automatic resurrection is refused")
    return MediaAck(
        event_id=receipt.event_id, producer_id=receipt.producer_id, receipt_id=receipt.id,
        alert_id=receipt.alert_id, evidence_id=receipt.evidence_id,
        media_id=attachment.media_id, evidence_status="READY", replayed=replayed)

def attach_evidence(db, event_id, producer, config, data, declared_sha256):
    if not re.fullmatch(r"[0-9a-f]{64}", declared_sha256 or ""):
        raise HTTPException(422, "A lowercase X-Evidence-SHA256 digest is required")
    if len(data) > MAX_MEDIA_BYTES:
        raise HTTPException(413, "JPEG exceeds 5MiB")
    actual_hash = hashlib.sha256(data).hexdigest()
    if actual_hash != declared_sha256:
        raise HTTPException(422, "Evidence digest does not match the uploaded bytes")
    from PIL import Image, UnidentifiedImageError
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format != "JPEG" or not (1 <= image.width <= 4096 and 1 <= image.height <= 4096):
                raise ValueError("Expected a bounded JPEG")
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise HTTPException(415, "Invalid or unsupported JPEG evidence") from error
    receipt = find_receipt(db, producer.producer_id, event_id)
    if receipt is None:
        raise HTTPException(404, "Producer event not found")
    if receipt.data_origin not in producer.allowed_origins or (
        producer.producer_instance_id is not None and receipt.producer_instance_id != producer.producer_instance_id
    ):
        raise HTTPException(403, "Producer is not authorized for this event")
    existing = db.get(AiEventAttachment, receipt.id)
    if existing is not None:
        if existing.sha256 != actual_hash:
            raise HTTPException(409, "Event already has a different evidence attachment")
        return _media_ack(db, receipt, existing, config, True), False
    try:
        attachment = AiEventAttachment(
            receipt_id=receipt.id, sha256=actual_hash, byte_length=len(data), created_at=now_utc())
        db.add(attachment)
        db.flush()
        relative = "ai/" + str(receipt.id) + "/" + actual_hash + ".jpg"
        target = _safe_media_path(config, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("xb") as handle:
                handle.write(data)
                handle.flush()
                import os
                os.fsync(handle.fileno())
        except FileExistsError:
            if hashlib.sha256(target.read_bytes()).hexdigest() != actual_hash:
                raise HTTPException(409, "Controlled media path contains different bytes")
        media = EvidenceMedia(
            evidence_id=receipt.evidence_id, media_type="image", file_path=relative,
            file_size=len(data), mime_type="image/jpeg", created_at=now_utc())
        db.add(media)
        db.flush()
        attachment.media_id = media.id
        evidence = db.get(Evidence, receipt.evidence_id)
        if evidence is None:
            raise HTTPException(410, "Event evidence metadata is missing")
        evidence.updated_at = now_utc()
        record_audit(db, None, "attach_ai_evidence", "evidence", evidence.id,
                     "producer=" + producer.producer_id + ";sha256=" + actual_hash)
        db.flush()
        response = _media_ack(db, receipt, attachment, config, False)
        db.commit()
        return response, True
    except IntegrityError as error:
        db.rollback()
        if not _unique_attachment_error(error):
            raise
        existing = db.get(AiEventAttachment, receipt.id)
        if existing is None:
            raise
        if existing.sha256 != actual_hash:
            raise HTTPException(409, "Event already has a different evidence attachment") from error
        return _media_ack(db, receipt, existing, config, True), False
    except Exception:
        # Files are intentionally retained as TEST artifacts on rollback.
        db.rollback()
        raise
