from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[2]
PROJECT_ENV = BASE_DIR.parent / "PythonProject1" / ".env"


class Settings(BaseSettings):
    mysql_host: str = Field("127.0.0.1", alias="MYSQL_HOST")
    mysql_port: int = Field(3306, alias="MYSQL_PORT")
    mysql_user: str = Field("reimbursement_app", alias="MYSQL_USER")
    mysql_password: str = Field("", alias="MYSQL_PASSWORD")
    mysql_database: str = Field("reimbursement_demo", alias="MYSQL_DATABASE")

    milvus_uri: str = Field("http://127.0.0.1:19530", alias="MILVUS_URI")
    milvus_token: str = Field("", alias="MILVUS_TOKEN")
    milvus_collection: str = Field(
        "reimbursement_knowledge_bge_small_zh_v1", alias="MILVUS_COLLECTION"
    )
    embedding_model: str = Field("BAAI/bge-small-zh-v1.5", alias="EMBEDDING_MODEL")
    embedding_path: str = Field("", alias="EMBEDDING_PATH")
    embedding_dim: int = Field(512, alias="EMBEDDING_DIM")

    dashscope_api_key: SecretStr = Field(default=SecretStr(""), alias="DASHSCOPE_API_KEY")
    llm_base_url: str = Field("https://dashscope.aliyuncs.com/compatible-mode/v1", alias="LLM_BASE_URL")
    llm_model: str = Field("qwen3.5-plus", alias="LLM_MODEL")
    llm_timeout: float = Field(45, gt=0, le=120, alias="LLM_TIMEOUT")
    llm_max_retries: int = Field(1, ge=0, le=2, alias="LLM_MAX_RETRIES")
    llm_trust_env: bool = Field(False, alias="LLM_TRUST_ENV")

    attachment_root: Path = BASE_DIR / "data" / "attachments"

    model_config = SettingsConfigDict(
        env_file=(str(PROJECT_ENV), str(BASE_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
