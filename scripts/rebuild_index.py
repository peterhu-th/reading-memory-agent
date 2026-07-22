import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingestion.build_index import rebuild_index


def main() -> None:
    count = rebuild_index()
    print(f"Indexed {count} chunks")


if __name__ == "__main__":
    main()
