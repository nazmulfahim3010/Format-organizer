import os
import uuid
from pathlib import Path

from ..config import settings


def new_path(kind: str, owner_id: int, ext: str) -> str:
    d = settings.data_dir / kind / str(owner_id)
    d.mkdir(parents=True, exist_ok=True)
    return str(d / f"{uuid.uuid4().hex}.{ext}")


def remove_quietly(path: str) -> None:
    try:
        p = Path(path).resolve()
        if settings.data_dir in p.parents:      # never delete outside the data dir
            os.remove(p)
    except OSError:
        pass
