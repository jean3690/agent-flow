import base64
import hashlib
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BASE_DIR.parent


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_env_file(BASE_DIR / ".env")
_load_env_file(REPO_DIR / "backend" / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


WEAK_JWT_SECRETS = {
    "agentflow-one-jwt-secret-key-change-me-to-a-long-random-string",
    "agentflow-dev-jwt-secret-key-only-for-development",
    "secret",
    "password",
    "123456",
    "jwt-secret",
    "your-secret-key",
    "default-secret",
}


@dataclass
class Settings:
    server_port: int = field(default_factory=lambda: _int("SERVER_PORT", 8084))
    mysql_host: str = field(default_factory=lambda: os.environ.get("MYSQL_HOST", "localhost"))
    mysql_port: int = field(default_factory=lambda: _int("MYSQL_PORT", 3306))
    mysql_database: str = field(default_factory=lambda: os.environ.get("MYSQL_DATABASE", "agent_flow"))
    mysql_username: str = field(default_factory=lambda: os.environ.get("MYSQL_USERNAME", "root"))
    mysql_password: str = field(default_factory=lambda: os.environ.get("MYSQL_PASSWORD", ""))

    redis_host: str = field(default_factory=lambda: os.environ.get("REDIS_HOST", "localhost"))
    redis_port: int = field(default_factory=lambda: _int("REDIS_PORT", 6379))
    redis_password: str = field(default_factory=lambda: os.environ.get("REDIS_PASSWORD", ""))

    jwt_secret: str = field(default_factory=lambda: os.environ.get("JWT_SECRET", "").strip())
    access_token_expiration_minutes: int = field(default_factory=lambda: _int("ACCESS_TOKEN_EXPIRATION_MINUTES", 120))
    refresh_token_expiration_hours: int = field(default_factory=lambda: _int("REFRESH_TOKEN_EXPIRATION_HOURS", 168))
    default_username: str = field(default_factory=lambda: os.environ.get("APP_AUTH_DEFAULT_USERNAME", "admin"))
    default_password: str = field(default_factory=lambda: os.environ.get("APP_AUTH_DEFAULT_PASSWORD", "admin123"))

    minio_endpoint: str = field(default_factory=lambda: os.environ.get("MINIO_ENDPOINT", "http://localhost:9000"))
    minio_access_key: str = field(default_factory=lambda: os.environ.get("MINIO_ACCESS_KEY", "minioadmin"))
    minio_secret_key: str = field(default_factory=lambda: os.environ.get("MINIO_SECRET_KEY", "minioadmin"))
    minio_bucket_name: str = field(default_factory=lambda: os.environ.get("MINIO_BUCKET_NAME", "agent-flow"))
    minio_public_url: str = field(default_factory=lambda: os.environ.get("MINIO_PUBLIC_URL", "http://localhost:9000"))

    cors_allowed_origin_patterns: str = field(
        default_factory=lambda: os.environ.get("CORS_ALLOWED_ORIGIN_PATTERNS", "http://localhost:*,http://127.0.0.1:*")
    )
    skills_path: str = field(default_factory=lambda: os.environ.get("SKILLS_PATH", ""))
    auto_migrate: bool = field(default_factory=lambda: os.environ.get("AGENTFLOW_AUTO_MIGRATE", "true").lower() != "false")
    database_url_override: str = field(default_factory=lambda: os.environ.get("AGENTFLOW_DATABASE_URL", ""))
    schema_sql_path: str = field(default_factory=lambda: os.environ.get("AGENTFLOW_SCHEMA_SQL", ""))

    def database_url(self) -> str:
        from urllib.parse import quote_plus

        if self.database_url_override:
            return self.database_url_override
        return (
            f"mysql+pymysql://{quote_plus(self.mysql_username)}:{quote_plus(self.mysql_password)}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}?charset=utf8mb4"
        )

    def resolve_jwt_secret(self) -> str:
        if self.jwt_secret and self.jwt_secret not in WEAK_JWT_SECRETS:
            return self.jwt_secret
        # Local development without an explicit strong secret: generate one per process,
        # mirroring the Java JwtSecretProvider behaviour.
        return base64.urlsafe_b64encode(secrets.token_bytes(48)).decode("ascii").rstrip("=")

    def resolve_schema_sql_path(self) -> Path:
        if self.schema_sql_path:
            return Path(self.schema_sql_path)
        repo_path = REPO_DIR / "backend" / "src" / "main" / "resources" / "schema.sql"
        if repo_path.is_file():
            return repo_path
        return BASE_DIR / "schema.sql"

    def resolve_skills_path(self) -> Path:
        if self.skills_path:
            candidate = Path(self.skills_path)
            if candidate.is_absolute():
                return candidate
            return (BASE_DIR / candidate).resolve()
        for candidate in (
            BASE_DIR / "skills",
            REPO_DIR / "backend" / "src" / "main" / "resources" / "skills",
        ):
            if candidate.is_dir():
                return candidate
        return BASE_DIR / "skills"


settings = Settings()
