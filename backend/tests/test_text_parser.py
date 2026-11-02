import pytest

from opsintel.parsers import ParseError, ParseResult, TextParser
from opsintel.parsers.text import split_lines


def parse(data: bytes, **kw):
    r = ParseResult()
    return list(TextParser(**kw).parse(data, r)), r


@pytest.mark.parametrize("sep", ["\n", "\r\n", "\r"])
def test_line_numbers_independent_of_line_endings(sep):
    data = sep.join(f"line {i}" for i in range(1, 26)).encode() + sep.encode()
    chunks, r = parse(data, chunk_lines=10)
    assert r.line_count == 25
    assert [(c.start_line, c.end_line) for c in chunks] == [(1, 10), (11, 20), (21, 25)]
    for c in chunks:
        lines = c.text.split("\n")
        assert lines[0] == f"line {c.start_line}"
        assert lines[-1] == f"line {c.end_line}"


def test_split_lines_ignores_unicode_separators():
    # str.splitlines() would break on \x0c and \u2028 and shift line numbers
    assert split_lines("a\x0cb\u2028c\nd") == ["a\x0cb\u2028c", "d"]


def test_blank_windows_are_dropped_but_numbering_kept():
    data = ("x\n" + "\n" * 15 + "y\n").encode()  # x on line 1, y on line 17
    chunks, _ = parse(data, chunk_lines=5)
    assert [(c.start_line, c.end_line, c.text) for c in chunks] == [(1, 5, "x\n\n\n\n"), (16, 17, "\ny")]


def test_long_line_split_keeps_line_number():
    data = ("short\n" + "a" * 25 + "\nend\n").encode()
    chunks, _ = parse(data, chunk_lines=10, max_chars=10)
    assert [(c.start_line, c.end_line, c.text) for c in chunks] == [
        (1, 1, "short"), (2, 2, "a" * 10), (2, 2, "a" * 10), (2, 2, "a" * 5), (3, 3, "end"),
    ]


def test_encodings():
    _, r = parse("caf\u00e9\n".encode("utf-8"))
    assert r.encoding == "utf-8"
    chunks, r = parse(b"\xef\xbb\xbfhello\n")
    assert r.encoding == "utf-8-sig" and chunks[0].text == "hello"
    chunks, r = parse("h\u00e9llo w\u00f6rld, \u00e7a va tr\u00e8s bien merci\n".encode("cp1252"))
    assert "\u00e9" in chunks[0].text
    chunks, r = parse("hi\nthere\n".encode("utf-16"))
    assert r.encoding == "utf-16" and chunks[0].text == "hi\nthere"


def test_binary_rejected():
    with pytest.raises(ParseError):
        parse(b"\x00\x01\x02binary")


def test_empty_file():
    chunks, r = parse(b"")
    assert chunks == [] and r.line_count == 0
