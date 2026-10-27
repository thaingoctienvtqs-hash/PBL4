"""Producer keys are separate from human JWTs and never logged."""
import hashlib
import secrets
from fastapi import Header, HTTPException, Request
from app.core.ai_ingest_config import Producer

def require_ai_producer(
    request: Request,
    credential: str | None = Header(default=None, alias="X-ArtGuard-Producer-Key"),
) -> Producer:
    if not credential or len(credential) > 512:
        raise HTTPException(401, "Producer authentication required")
    digest = hashlib.sha256(credential.encode("utf-8")).hexdigest()
    principal = None
    for producer in request.app.state.integration_config.producers:
        if secrets.compare_digest(producer.token_sha256, digest):
            principal = producer
    if principal is None:
        raise HTTPException(401, "Invalid producer credential")
    return principal
