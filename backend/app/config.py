from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VQI_", env_file=".env", extra="ignore")

    data_dir: Path = Path("./data")
    max_duration_seconds: int = 90 * 60
    max_upload_bytes: int = 20 * 1024 * 1024 * 1024
    max_image_upload_bytes: int = 500 * 1024 * 1024
    max_remote_bytes: int = 12 * 1024 * 1024 * 1024
    max_image_files: int = 100
    max_image_pixels: int = 16_000_000
    max_document_pages: int = 20
    ffmpeg_threads: int = 2
    chunk_size_bytes: int = 1024 * 1024
    retention_hours: int = 24
    worker_count: int = 1
    direct_download_connections: int = 8
    youtube_concurrent_fragments: int = 8

    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    x264_crf_fast: int = 21
    x264_crf_balanced: int = 19
    x264_crf_quality: int = 18
    nvenc_cq_fast: int = 22
    nvenc_cq_balanced: int = 20
    nvenc_cq_quality: int = 18
    qsv_quality_fast: int = 24
    qsv_quality_balanced: int = 21
    qsv_quality_quality: int = 18
    hardware_cache_seconds: int = 300

    max_input_width: int = 1920
    max_input_height: int = 1080
    allowed_video_extensions: str = ".mp4,.mov,.mkv,.webm,.m4v,.avi,.mts,.m2ts,.ts"
    allowed_image_extensions: str = ".jpg,.jpeg,.png,.webp,.bmp,.tif,.tiff,.gif,.avif"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,https://localhost"
    api_key: str = ""
    app_password_hash: str = ""
    session_secret: str = ""

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def outputs_dir(self) -> Path:
        return self.data_dir / "outputs"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "jobs.sqlite3"

    @property
    def allowed_video_extension_set(self) -> set[str]:
        return {item.strip().lower() for item in self.allowed_video_extensions.split(",") if item.strip()}

    @property
    def allowed_image_extension_set(self) -> set[str]:
        return {item.strip().lower() for item in self.allowed_image_extensions.split(",") if item.strip()}

    @property
    def allowed_remote_extension_set(self) -> set[str]:
        return self.allowed_video_extension_set | self.allowed_image_extension_set | {".mp3", ".m4a", ".wav", ".flac"}

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


settings = Settings()
