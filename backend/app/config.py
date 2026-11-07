import os
from pathlib import Path


class Settings:
    def __init__(self) -> None:
        root = Path(__file__).resolve().parent.parent
        self.env = os.getenv("SMARTDOC_ENV", "development")
        self.data_dir = Path(os.getenv("SMARTDOC_DATA_DIR", root / "storage")).resolve()
        self.database_url = os.getenv("SMARTDOC_DATABASE_URL", f"sqlite:///{self.data_dir / 'smartdoc.db'}")
        self.secret = os.getenv("SMARTDOC_SECRET", "dev-secret-change-me")
        self.cors_origins = [o.strip() for o in os.getenv("SMARTDOC_CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
        self.allow_registration = os.getenv("SMARTDOC_ALLOW_REGISTRATION", "1") == "1"
        self.heavy_calls_per_minute = int(os.getenv("SMARTDOC_HEAVY_CALLS_PER_MINUTE", "60"))
        self.login_attempts_per_minute = int(os.getenv("SMARTDOC_LOGIN_ATTEMPTS_PER_MINUTE", "10"))
        self.max_paste_images = int(os.getenv("SMARTDOC_MAX_PASTE_IMAGES", "50"))
        self.keep_generated_files = int(os.getenv("SMARTDOC_KEEP_GENERATED_FILES", "20"))
        self.frontend_dist = os.getenv("SMARTDOC_FRONTEND_DIST", str(root.parent / "frontend" / "dist"))
        if self.env == "production" and (self.secret == "dev-secret-change-me" or len(self.secret) < 32):
            raise RuntimeError("Set SMARTDOC_SECRET to a random value of at least 32 characters in production.")
        for sub in ("templates", "media", "generated"):
            (self.data_dir / sub).mkdir(parents=True, exist_ok=True)


settings = Settings()
