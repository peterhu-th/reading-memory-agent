import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.models.schemas import TextChunk


def safe_text(text: str) -> str:
    return text.encode("ascii", errors="backslashreplace").decode("ascii")


def load_jsonl(path: str) -> list[TextChunk]:
    input_path = Path(path)
    if not input_path.exists():
        return []

    chunks: list[TextChunk] = []
    with input_path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            chunks.append(TextChunk(**json.loads(line)))
    return chunks


def main() -> None:
    settings = get_settings()
    chunks = load_jsonl(settings.CHUNKS_JSONL_PATH)
    if not chunks:
        print(f"No chunks found at {settings.CHUNKS_JSONL_PATH}")
        return

    sample = random.sample(chunks, min(10, len(chunks)))
    for chunk in sample:
        print("=" * 80)
        print(f"chunk_id: {safe_text(chunk.chunk_id)}")
        print(f"title: {safe_text(chunk.title)}")
        print(f"author: {safe_text(chunk.author or 'unknown')}")
        print(f"chapter: {safe_text(str(chunk.chapter_title or chunk.chapter_index))}")
        print(safe_text(chunk.text[:500]))


if __name__ == "__main__":
    main()
