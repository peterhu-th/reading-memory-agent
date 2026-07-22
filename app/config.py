import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# 把 .env 文件内容加载进当前程序的环境变量
load_dotenv()


class Settings(BaseModel):
    """Runtime settings loaded from environment variables."""

    OPENAI_API_KEY: str = Field(min_length=1)
    OPENAI_BASE_URL: str = Field(min_length=1)
    CHAT_MODEL: str = Field(default="gpt-5.4", min_length=1)
    EMBEDDING_MODEL: str = Field(default="text-embedding-3-small", min_length=1)
    # 向量索引文件
    VECTOR_DB_PATH: str = "./data/index/chroma"
    RAW_EPUB_DIR: str = "./data/raw/epub"
    BOOKS_JSONL_PATH: str = "./data/processed/books_jsonl/books.jsonl"
    CHUNKS_JSONL_PATH: str = "./data/processed/chunks_jsonl/chunks.jsonl"
    CHROMA_COLLECTION: str = "reading_memory_chunks"

# 缓存装饰器：第一次运行创建 Setting 对象，后续调用直接返回创建好的对象
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached project settings."""

    return Settings(
        OPENAI_API_KEY=os.getenv("OPENAI_API_KEY", ""),
        OPENAI_BASE_URL=os.getenv("OPENAI_BASE_URL", ""),
        CHAT_MODEL=os.getenv("CHAT_MODEL", "gpt-5.4"),
        EMBEDDING_MODEL=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
        VECTOR_DB_PATH=os.getenv("VECTOR_DB_PATH", "./data/index/chroma"),
        RAW_EPUB_DIR=os.getenv("RAW_EPUB_DIR", "./data/raw/epub"),
        BOOKS_JSONL_PATH=os.getenv(
            "BOOKS_JSONL_PATH",
            "./data/processed/books_jsonl/books.jsonl",
        ),
        CHUNKS_JSONL_PATH=os.getenv(
            "CHUNKS_JSONL_PATH",
            "./data/processed/chunks_jsonl/chunks.jsonl",
        ),
        CHROMA_COLLECTION=os.getenv("CHROMA_COLLECTION", "reading_memory_chunks"),
    )
