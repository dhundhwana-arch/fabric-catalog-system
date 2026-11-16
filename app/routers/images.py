"""Image reference + upload management.

Images are stored on disk under UPLOAD_DIR (provider-independent). The
database only stores the URL + storage reference — never image binaries.
"""
from __future__ import annotations

import hashlib
import io
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.config import get_settings
from app.database import get_db
from app.id_generator import next_id
from app.models import FabricImage, ImageType
from app.schemas import ImageCreate, ImageOut
from app.services import get_fabric_or_404, get_variant_or_404

router = APIRouter(tags=["images"])

MAGIC = {
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/png": [b"\x89PNG"],
    "image/webp": [b"RIFF"],
}
EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


def _validate_upload(file: UploadFile, settings) -> bytes:
    if file.content_type not in settings.allowed_image_types:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {file.content_type}")
    # Read with a hard cap so an oversized body is never fully buffered.
    data = file.file.read(settings.max_upload_bytes + 1)
    if len(data) == 0:
        raise HTTPException(status_code=422, detail="Empty file")
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="File exceeds maximum size")
    prefixes = MAGIC.get(file.content_type, [])
    if prefixes and not any(data.startswith(p) for p in prefixes):
        raise HTTPException(status_code=422, detail="File content does not match declared type")
    return data


def _verify_decodable(data: bytes) -> None:
    """Reject files whose bytes are not a real, non-huge image.

    Magic bytes alone can be faked; decoding also caps pixel dimensions so
    a tiny "decompression bomb" cannot exhaust server memory when the
    asset is later processed by another module.
    """
    try:
        from PIL import Image  # optional dependency

        with Image.open(io.BytesIO(data)) as img:
            width, height = img.size
            img.verify()
        if width * height > settings_max_pixels():
            raise HTTPException(status_code=413, detail="Image dimensions too large")
    except HTTPException:
        raise
    except ImportError:
        return  # Pillow absent: magic-byte + size checks still apply
    except Exception:
        raise HTTPException(status_code=422, detail="File is not a decodable image")


def settings_max_pixels() -> int:
    return 40_000_000  # 40 MP


def _save_upload(data: bytes, content_type: str, settings) -> tuple[str, str]:
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    # Safe generated name — never trust the user-provided filename.
    digest = hashlib.sha256(data).hexdigest()[:16]
    safe_name = f"{uuid.uuid4().hex[:8]}-{digest}{EXT[content_type]}"
    path = upload_dir / safe_name
    path.write_bytes(data)
    return f"/uploads/{safe_name}", str(path)


@router.post("/images", response_model=ImageOut, status_code=201, dependencies=[Depends(require_admin)])
def register_image(payload: ImageCreate, db: Session = Depends(get_db)):
    if payload.fabric_id is None and payload.variant_id is None:
        raise HTTPException(status_code=422, detail="Either fabric_id or variant_id is required")
    if payload.fabric_id is not None:
        get_fabric_or_404(db, payload.fabric_id)
    if payload.variant_id is not None:
        get_variant_or_404(db, payload.variant_id)
    img = FabricImage(
        image_id=next_id(db, "image"),
        fabric_id=payload.fabric_id,
        variant_id=payload.variant_id,
        image_url=payload.image_url,
        storage_reference=payload.storage_reference,
        image_type=payload.image_type,
        image_description=payload.image_description,
        is_primary=payload.is_primary,
    )
    db.add(img)
    db.commit()
    db.refresh(img)
    return img


@router.post("/images/upload", response_model=ImageOut, status_code=201, dependencies=[Depends(require_admin)])
def upload_image(
    file: UploadFile = File(...),
    fabric_id: int | None = Form(default=None),
    variant_id: int | None = Form(default=None),
    image_type: ImageType = Form(default=ImageType.OTHER),
    image_description: str | None = Form(default=None),
    is_primary: bool = Form(default=False),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    if fabric_id is None and variant_id is None:
        raise HTTPException(status_code=422, detail="Either fabric_id or variant_id is required")
    if fabric_id is not None:
        get_fabric_or_404(db, fabric_id)
    if variant_id is not None:
        get_variant_or_404(db, variant_id)
    data = _validate_upload(file, settings)
    _verify_decodable(data)
    url, ref = _save_upload(data, file.content_type, settings)
    img = FabricImage(
        image_id=next_id(db, "image"),
        fabric_id=fabric_id,
        variant_id=variant_id,
        image_url=url,
        storage_reference=ref,
        image_type=image_type,
        image_description=image_description,
        is_primary=is_primary,
    )
    db.add(img)
    db.commit()
    db.refresh(img)
    return img


@router.get("/fabrics/{fabric_pk}/images", response_model=list[ImageOut])
def fabric_images(fabric_pk: int, db: Session = Depends(get_db)):
    get_fabric_or_404(db, fabric_pk)
    return db.execute(
        select(FabricImage).where(FabricImage.fabric_id == fabric_pk).order_by(FabricImage.is_primary.desc())
    ).scalars().all()


@router.get("/variants/{variant_pk}/images", response_model=list[ImageOut])
def variant_images(variant_pk: int, db: Session = Depends(get_db)):
    get_variant_or_404(db, variant_pk)
    return db.execute(
        select(FabricImage).where(FabricImage.variant_id == variant_pk).order_by(FabricImage.is_primary.desc())
    ).scalars().all()


@router.delete("/images/{image_pk}", dependencies=[Depends(require_admin)])
def delete_image(image_pk: int, db: Session = Depends(get_db)):
    img = db.get(FabricImage, image_pk)
    if img is None:
        raise HTTPException(status_code=404, detail="Image not found")
    db.delete(img)
    db.commit()
    return {"message": "Image reference deleted"}
