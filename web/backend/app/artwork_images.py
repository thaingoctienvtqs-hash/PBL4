from __future__ import annotations

import logging
import mimetypes
import os
import re
import warnings
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.db import get_db
from app.dependencies import require_roles
from app.models import Artwork, User

logger = logging.getLogger("artguard.artwork_images")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ARTWORK_UPLOAD_DIR = BACKEND_ROOT / "uploads" / "artworks"
STAGING_DIR = BACKEND_ROOT / "uploads" / ".artwork-image-staging"
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 30_000_000
IMAGE_FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
MANAGED_IMAGE_PATH = re.compile(r"^/uploads/artworks/[0-9a-f]{32}\.(?:jpg|png|webp)$")
mimetypes.add_type("image/jpeg", ".jpg")
mimetypes.add_type("image/png", ".png")
mimetypes.add_type("image/webp", ".webp")

router = APIRouter(tags=["artwork images"])


def is_managed_artwork_image(image_url: str | None) -> bool:
    return bool(image_url and MANAGED_IMAGE_PATH.fullmatch(image_url))


def delete_managed_artwork_image(image_url: str | None) -> None:
    """Remove only generated, direct-child files in this feature's upload folder."""
    if not is_managed_artwork_image(image_url):
        return
    filename = image_url.rsplit("/", 1)[-1]
    root = ARTWORK_UPLOAD_DIR.resolve()
    candidate = (ARTWORK_UPLOAD_DIR / filename).resolve()
    if candidate.parent != root:
        return
    try:
        candidate.unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not remove managed artwork image %s", filename)


def validate_image(data: bytes) -> tuple[str, str]:
    if not data:
        raise HTTPException(status_code=415, detail="Tệp tải lên không phải ảnh JPEG, PNG hoặc WebP hợp lệ")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                image_format = image.format
                width, height = image.size
                if image_format not in IMAGE_FORMATS:
                    raise HTTPException(status_code=415, detail="Chỉ chấp nhận ảnh JPEG, PNG hoặc WebP")
                if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                    raise HTTPException(status_code=413, detail="Kích thước ảnh vượt giới hạn an toàn")
                image.verify()
            with Image.open(BytesIO(data)) as image:
                image.load()
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(status_code=415, detail="Tệp tải lên không phải ảnh JPEG, PNG hoặc WebP hợp lệ") from None
    return image_format, IMAGE_FORMATS[image_format]


@router.post("/artworks/{artwork_id}/image")
async def upload_artwork_image(
    artwork_id: int,
    file: UploadFile = File(...),
    user: User = Depends(require_roles("admin", "manager")),
    db: Session = Depends(get_db),
):
    artwork = db.get(Artwork, artwork_id)
    if artwork is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy tranh")

    data = await file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Dung lượng ảnh tối đa là 5 MB")
    _, extension = validate_image(data)

    filename = f"{uuid4().hex}{extension}"
    image_url = f"/uploads/artworks/{filename}"
    old_image_url = artwork.image_url
    staged_file = STAGING_DIR / filename
    final_file = ARTWORK_UPLOAD_DIR / filename
    try:
        STAGING_DIR.mkdir(parents=True, exist_ok=True)
        ARTWORK_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        with staged_file.open("xb") as output:
            output.write(data)
        os.replace(staged_file, final_file)
        artwork.image_url = image_url
        record_audit(db, user, "upload_image", "artwork", artwork.id, filename)
        db.commit()
    except Exception:
        db.rollback()
        staged_file.unlink(missing_ok=True)
        final_file.unlink(missing_ok=True)
        logger.error("Artwork image upload failed for artwork id %s", artwork_id)
        raise HTTPException(status_code=500, detail="Không thể lưu ảnh. Ảnh hiện tại vẫn được giữ nguyên.") from None

    if old_image_url != image_url:
        delete_managed_artwork_image(old_image_url)
    return {"image_url": artwork.image_url}
