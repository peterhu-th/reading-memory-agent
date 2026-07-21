from pydantic import BaseModel, Field


class BookParagraph(BaseModel):
    """A normalized paragraph extracted from one EPUB document."""

    book_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    author: str = ""
    source_path: str = Field(min_length=1)
    chapter_index: int = Field(ge=0)
    chapter_title: str = ""
    paragraph_index: int = Field(ge=0)
    text: str = Field(min_length=1)


class TextChunk(BaseModel):
    """A retrievable text chunk with enough metadata for citation."""

    chunk_id: str = Field(min_length=1)
    book_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    author: str = ""
    chapter_index: int = Field(ge=0)
    chapter_title: str = ""
    chunk_index: int = Field(ge=0)
    start_paragraph_index: int = Field(ge=0)
    end_paragraph_index: int = Field(ge=0)
    text: str = Field(min_length=1)


class RetrievedChunk(BaseModel):
    """A chunk returned by retrieval, optionally with a similarity score."""

    chunk: TextChunk
    score: float | None = None


class AnswerWithCitations(BaseModel):
    """The final generated answer plus program-built citation strings."""

    answer: str = Field(min_length=1)
    citations: list[str] = Field(default_factory=list)
