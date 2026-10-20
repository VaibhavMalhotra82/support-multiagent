import os
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    # LLM Configuration
    openai_api_key: Optional[str] = None
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.5

    # LangSmith Configuration
    langsmith_enabled: bool = False
    langsmith_api_key: Optional[str] = None
    langsmith_project: str = "support-multiagent"

    # Vector Store Configuration
    vector_store_type: str = "chroma"  # Options: chroma, weaviate, pinecone
    chroma_path: str = "./chroma_db"
    chroma_collection: str = "support_docs"
    chroma_memory_collection: str = "support_memory"
    retrieval_top_k: int = 5

    # Database Configuration
    database_url: str = "sqlite:///./support_agent.db"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    def now(self):
        from datetime import datetime
        return datetime.utcnow()


settings = Settings()


def init_langsmith():
    """Initialize LangSmith if enabled."""
    if settings.langsmith_enabled and settings.langsmith_api_key:
        os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
        os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
        os.environ["LANGSMITH_TRACING_V2"] = "true"
