from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_CHECKOUT_ROOT = _BACKEND_DIR.parent
# A git checkout has frontend/ next to backend/. The container copies backend/ to /srv.
REPO_ROOT = _CHECKOUT_ROOT if (_CHECKOUT_ROOT / "frontend").is_dir() else _BACKEND_DIR
EMBEDDING_DIM = 1536


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT / ".env"), str(REPO_ROOT / "backend" / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "local"
    app_name: str = "ManualMind"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8091
    auto_migrate: bool = True

    database_url: str = "postgresql+psycopg://manualmind:manualmind@127.0.0.1:5432/manualmind"
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    db_sslmode: str = "prefer"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_fallback_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = EMBEDDING_DIM
    llm_answers: bool = True

    mcp_server_url: str = "http://127.0.0.1:8092/mcp"
    mcp_server_token: str = ""
    mcp_tool_timeout_seconds: float = 8.0
    node_timeout_seconds: float = 25.0

    cors_allowed_origins: str = "http://127.0.0.1:4178,http://localhost:4178"
    cors_allow_vercel_previews: bool = True

    object_storage_bucket: str = ""
    object_storage_endpoint: str = ""
    object_storage_access_key: str = ""
    object_storage_secret_key: str = ""
    object_storage_region: str = "us-east-1"
    storage_local_path: str = str(REPO_ROOT / ".storage")

    session_secret: str = "dev-only-change-me"
    default_tenant_id: str = "demo"
    retention_days: int = 365

    seed_demo_data: bool = True
    embed_worker: bool = True
    max_upload_bytes: int = 25 * 1024 * 1024

    vector_top_k: int = 12
    bm25_top_k: int = 12
    rrf_k: int = 60
    rrf_weight_vector: float = 1.0
    rrf_weight_bm25: float = 1.0
    rerank_pool: int = 12
    return_k: int = 6

    confidence_high: float = 0.80
    confidence_medium: float = 0.60
    weak_relevance_threshold: float = 0.35

    chunk_target_tokens: int = 700
    chunk_min_tokens: int = 500
    chunk_max_tokens: int = 800
    chunk_overlap_tokens: int = 100

    prompt_version: str = "answer-v1"
    input_cost_per_million: float = 0.15
    output_cost_per_million: float = 0.60
    embedding_cost_per_million: float = 0.02

    oem_api_base_url: str = ""
    oem_api_schema_version: str = ""
    oem_api_token: str = ""

    public_base_url: str = ""

    dev_origins: str = Field(default="")

    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.cors_allowed_origins.split(",") if item.strip()]

    def object_storage_configured(self) -> bool:
        return bool(
            self.object_storage_bucket
            and self.object_storage_endpoint
            and self.object_storage_access_key
            and self.object_storage_secret_key
        )

    def openai_configured(self) -> bool:
        return bool(self.openai_api_key.strip())

    def psycopg_url(self) -> str:
        url = self.database_url
        for prefix in ("postgresql+psycopg://", "postgresql+psycopg2://"):
            if url.startswith(prefix):
                url = "postgresql://" + url[len(prefix) :]
        return url

    def production_problems(self) -> list[str]:
        if self.app_env != "production":
            return []
        problems: list[str] = []
        if not self.database_url or "manualmind:manualmind" in self.database_url:
            problems.append("DATABASE_URL must be a managed Postgres URL in production.")
        if self.session_secret in {"", "dev-only-change-me", "replace-with-secret-store-value"}:
            problems.append("SESSION_SECRET must come from a secret store, not the example value.")
        if not self.cors_origins():
            problems.append("CORS_ALLOWED_ORIGINS must list exact frontend origins.")
        if not self.object_storage_configured():
            problems.append(
                "OBJECT_STORAGE_BUCKET, OBJECT_STORAGE_ENDPOINT, OBJECT_STORAGE_ACCESS_KEY, "
                "and OBJECT_STORAGE_SECRET_KEY are required. Do not store uploads on ephemeral disk."
            )
        if not self.mcp_server_url:
            problems.append("MCP_SERVER_URL is required.")
        if self.embedding_dimensions != EMBEDDING_DIM:
            problems.append(
                f"EMBEDDING_DIMENSIONS must stay {EMBEDDING_DIM} to match the pgvector column."
            )
        if self.db_sslmode not in {"require", "verify-ca", "verify-full"}:
            problems.append("DB_SSLMODE must be require, verify-ca, or verify-full in production.")
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()
