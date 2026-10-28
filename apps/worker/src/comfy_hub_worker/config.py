from pathlib import Path
from typing import Self
from urllib.parse import urlparse
from uuid import UUID

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    cloud_api_base_url: AnyHttpUrl
    worker_id: UUID
    worker_api_token: SecretStr
    comfyui_base_url: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:8188")
    h3_comfyui_base_url: AnyHttpUrl | None = None
    image_generation_enabled: bool = True
    director_enabled: bool = False
    poll_interval_seconds: float = Field(default=5, ge=1, le=300)
    max_concurrent_jobs: int = Field(default=1, ge=1, le=8)
    workflow_directory: Path = Path("../../workflows")
    worker_state_directory: Path = Path("./worker-state")

    @field_validator("worker_api_token")
    @classmethod
    def nonempty_token(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value().strip()) < 32:
            raise ValueError("WORKER_API_TOKEN 至少需要 32 个字符")
        return value

    @model_validator(mode="after")
    def validate_endpoints(self) -> Self:
        for url in (self.cloud_api_base_url, self.comfyui_base_url, self.h3_comfyui_base_url):
            if url is None:
                continue
            if url.username or url.password or url.query or url.fragment:
                raise ValueError("服务地址不得包含凭证、查询参数或片段")
        cloud = urlparse(str(self.cloud_api_base_url))
        if cloud.scheme != "https" and cloud.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("云端连接必须使用 HTTPS，仅本机开发允许 HTTP")
        if self.h3_comfyui_base_url:
            remote = urlparse(str(self.h3_comfyui_base_url))
            local = remote.hostname in {"localhost", "127.0.0.1", "::1"}
            private = remote.scheme == "https" and (remote.hostname or "").endswith(".ts.net")
            if not local and not private:
                raise ValueError("H3 服务只允许本机回环地址或 Tailscale 私网 HTTPS 地址")
        if not self.workflow_directory.is_dir():
            raise ValueError("WORKFLOW_DIRECTORY 必须指向存在的目录")
        return self
