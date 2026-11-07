import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ...core.uploads import MAX_IMAGE_BYTES, UploadRejected, sanitize_image
from ...database.session import get_db
from ...models.db import MediaAsset, User
from ...services import storage
from ..deps import current_user, heavy, owned

router = APIRouter(prefix="/api/media", tags=["media"])


def save_image(db: Session, user: User, data: bytes) -> MediaAsset:
    try:
        clean, ext, w, h = sanitize_image(data)
    except UploadRejected as e:
        raise HTTPException(422, str(e))
    path = storage.new_path("media", user.id, ext)
    with open(path, "wb") as f:
        f.write(clean)
    a = MediaAsset(id=uuid.uuid4().hex, owner_id=user.id, path=path,
                   mime="image/jpeg" if ext == "jpg" else "image/png", width=w, height=h)
    db.add(a)
    db.commit()
    return a


@router.post("/upload", dependencies=[Depends(heavy)])
def upload(file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = save_image(db, user, file.file.read(MAX_IMAGE_BYTES + 1))
    return {"asset_id": a.id, "width": a.width, "height": a.height}


@router.get("/{asset_id}")
def get_image(asset_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = owned(db, MediaAsset, asset_id, user)
    return FileResponse(a.path, media_type=a.mime, headers={"Cache-Control": "private, max-age=3600"})
