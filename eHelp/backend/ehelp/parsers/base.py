from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Chunk:
    ordinal: int
    text: str
    coord_kind: str  # line | page | section | cell | row
    start_line: int | None = None
    end_line: int | None = None
    page: int | None = None
    sheet: str | None = None
    cell_ref: str | None = None
    row_num: int | None = None
    section_path: str | None = None
    key_path: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass(slots=True)
class ParseResult:
    encoding: str | None = None
    line_count: int | None = None
    warnings: list[str] = field(default_factory=list)


class Parser(Protocol):
    name: str
    version: str
    # Run in the sandbox process (with timeout) and cache results; true for third-party document libraries.
    isolated: bool

    @property
    def signature(self) -> str: ...

    def spec(self) -> tuple[str, dict]: ...

    def parse(self, data: bytes, result: ParseResult) -> Iterator[Chunk]: ...


class ParseError(Exception):
    """Content cannot be extracted (malformed, encrypted, binary or undecodable)."""


def bounded_groups(lines: list[str], max_lines: int, max_chars: int) -> Iterator[tuple[int, int]]:
    """Yield [start, end) index ranges of at most max_lines lines and roughly max_chars characters."""
    start, size = 0, 0
    for i, line in enumerate(lines):
        if i > start and (i - start >= max_lines or size + len(line) + 1 > max_chars):
            yield start, i
            start, size = i, 0
        size += len(line) + 1
    if start < len(lines):
        yield start, len(lines)
