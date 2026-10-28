"""AI producer ingest plus human-authenticated integration metadata."""
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.routing import APIRoute
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from app.ai_event_models import AiEventReceipt
from app.ai_event_schemas import AiEventAck, AiEventIn, MediaAck
from app.core.ai_ingest_config import Producer
from app.core.producer_auth import require_ai_producer
from app.db import get_db
from app.dependencies import get_current_user
from app.models import User
from app.services.ai_event_ingest import (
    MAX_MEDIA_BYTES, attach_evidence, evidence_status, ingest_event)

class BoundedMetadataRoute(APIRoute):
    """Reject oversize/chunked metadata before Pydantic parses JSON."""
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def bounded(request):
            if request.method == "POST" and request.url.path.endswith("/ai/events"):
                length = request.headers.get("content-length")
                if length is not None:
                    if not length.isascii() or not length.isdigit():
                        raise HTTPException(400, "Invalid Content-Length")
                    if int(length) > 65536:
                        raise HTTPException(413, "Event metadata exceeds 64KiB")
                data = bytearray()
                async for chunk in request.stream():
                    if len(data) + len(chunk) > 65536:
                        raise HTTPException(413, "Event metadata exceeds 64KiB")
                    data.extend(chunk)
                # Starlette's body cache lets the normal FastAPI handler parse
                # exactly the received bytes once; business input is unchanged.
                request._body = bytes(data)
            return await handler(request)
        return bounded

router = APIRouter(prefix="/ai", tags=["isolated AI integration"], route_class=BoundedMetadataRoute)

@router.post("/events", response_model=AiEventAck, status_code=201)
def receive_event(
    payload: AiEventIn, request: Request, response: Response,
    producer: Producer = Depends(require_ai_producer), db: Session = Depends(get_db),
):
    result, created = ingest_event(db, payload, producer, request.app.state.integration_config)
    response.status_code = 201 if created else 200
    return result

@router.put("/events/{event_id}/evidence", response_model=MediaAck, status_code=201)
async def receive_evidence(
    event_id: UUID, request: Request, response: Response,
    declared_sha256: str | None = Header(default=None, alias="X-Evidence-SHA256"),
    producer: Producer = Depends(require_ai_producer), db: Session = Depends(get_db),
):
    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "image/jpeg":
        raise HTTPException(415, "Content-Type must be image/jpeg")
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_MEDIA_BYTES:
            raise HTTPException(413, "JPEG exceeds 5MiB")
    result, created = await run_in_threadpool(
        attach_evidence, db, event_id, producer, request.app.state.integration_config,
        bytes(data), declared_sha256)
    response.status_code = 201 if created else 200
    return result

@router.get("/alert-origins")
def alert_origins(
    alert_ids: str, request: Request,
    _: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    parts = alert_ids.split(",")
    if len(parts) > 100 or not parts or any(not p.isascii() or not p.isdigit() or int(p) <= 0 for p in parts):
        raise HTTPException(422, "Provide 1 to 100 positive alert IDs")
    ids = list(dict.fromkeys(int(p) for p in parts))
    rows = db.scalars(select(AiEventReceipt).where(AiEventReceipt.alert_id.in_(ids))).all()
    config = request.app.state.integration_config
    return {"items": [{
        "alert_id": row.alert_id, "receipt_id": row.id, "event_id": row.event_id,
        "producer_id": row.producer_id, "producer_instance_id": row.producer_instance_id,
        "source_event_id": row.source_event_id, "data_origin": row.data_origin,
        "evidence_id": row.evidence_id, "evidence_status": evidence_status(db, row, config),
    } for row in rows]}

@router.get("/status")
def integration_status(request: Request, _: User = Depends(get_current_user)):
    config = request.app.state.integration_config
    return {"enabled": True, "profile": config.profile,
            "database_name": config.database["name"], "database_kind": config.database["kind"],
            "data_mode": "integration_test"}
