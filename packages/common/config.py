from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    inference_mode: Literal["fixture", "live"] = "fixture"
    database_url: str = "postgresql+psycopg://video2robot:video2robot@localhost:55432/video2robot"
    redis_url: str = "redis://localhost:56379/0"
    s3_endpoint: str = "http://localhost:59000"
    s3_public_endpoint: str = "http://localhost:59000"
    s3_access_key: str = "local-video2robot"
    s3_secret_key: str = "local-video2robot-secret"
    s3_bucket: str = "video2robot"
    api_public_url: str = "http://localhost:58000"
    web_origin: str = "http://127.0.0.1:53000"
    model_api_key: str = ""
    meta_base_url: str = "https://api.meta.ai/v1"
    muse_model: str = "muse-spark-1.3"
    sam_model: str = "sam-3.1"
    geometry_python: str = ""
    vggt_checkpoint: str = ""
    sam3d_body_checkpoint: str = ""
    sam3d_mhr_path: str = ""
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    processing_fps: int = 15
    max_upload_bytes: int = 524288000
    min_duration: float = 10
    max_duration: float = 120
    max_model_calls: int = 16
    stage_timeout_seconds: int = 900


@lru_cache
def settings() -> Settings:
    return Settings()

