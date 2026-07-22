import re


def normalize_whitespace(text: str) -> str:
    text = text.replace("\ufffd", "")
    return re.sub(r"\s+", " ", text).strip()


def is_useful_paragraph(text: str, min_length: int = 10) -> bool:
    normalized = normalize_whitespace(text)
    return len(normalized) >= min_length
