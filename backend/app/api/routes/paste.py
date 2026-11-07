from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...database.session import get_db
from ...models.db import User
from ...paste.normalizer import normalize
from ...schemas.api import PasteIn, PasteOut
from ...schemas.content import SectionBox
from ...config import settings
from ..deps import current_user, heavy
from .media import save_image

router = APIRouter(prefix="/api/paste", tags=["paste"])


def _resolve_images(boxes, mapping):
    for b in boxes:
        if isinstance(b, SectionBox):
            _resolve_images(b.content, mapping)
        elif b.type == "figure" and b.src and b.src.startswith("pending:"):
            b.asset_id = mapping.get(int(b.src.split(":")[1]))
            b.src = None


@router.post("/normalize", response_model=PasteOut, dependencies=[Depends(heavy)])
def normalize_paste(body: PasteIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Turn clipboard HTML / Markdown / text into boxes. Pasted images are saved as sanitized assets."""
    res = normalize(text=body.text, html=body.html, fmt=body.format)
    mapping = {}
    if len(res.images) > settings.max_paste_images:
        res.warnings.append({"code": "TOO_MANY_IMAGES",
                             "message": f"Only the first {settings.max_paste_images} pasted images were kept."})
    for img in res.images[:settings.max_paste_images]:
        try:
            mapping[img.index] = save_image(db, user, img.data).id
        except Exception:
            res.warnings.append({"code": "FIGURE_REJECTED", "message": "A pasted image was rejected (unsupported or too large)."})
    _resolve_images(res.boxes, mapping)
    return PasteOut(boxes=[b.model_dump() for b in res.boxes], title=res.title,
                    warnings=res.warnings, source_format=res.source_format)
