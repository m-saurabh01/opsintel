import multiprocessing
from multiprocessing.connection import Connection

from ehelp.parsers.base import Chunk, ParseError, Parser, ParseResult


class ParseTimeout(Exception):
    pass


class ParserCrashed(Exception):
    pass


def _child_main(conn: Connection) -> None:
    from ehelp.parsers.registry import build

    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            return
        if msg is None:
            return
        name, kwargs, data = msg
        result = ParseResult()
        try:
            chunks = list(build(name, kwargs).parse(data, result))
            conn.send(("ok", chunks, result))
        except ParseError as exc:
            conn.send(("parse_error", str(exc), None))
        except Exception as exc:
            conn.send(("error", f"{type(exc).__name__}: {exc}", None))


class ParserSandbox:
    """Runs third-party document parsers in a separate process so hangs, crashes and memory blow-ups are contained.

    Uses the `spawn` start method on every OS (the only one available on Windows).
    """

    def __init__(self, timeout_s: float):
        self.timeout_s = timeout_s
        self._ctx = multiprocessing.get_context("spawn")
        self._proc = None
        self._conn: Connection | None = None

    def run(self, parser: Parser, data: bytes) -> tuple[list[Chunk], ParseResult]:
        if self._proc is None or not self._proc.is_alive():
            self._start()
        assert self._conn is not None
        name, kwargs = parser.spec()
        try:
            self._conn.send((name, kwargs, data))
            ready = self._conn.poll(self.timeout_s)
        except (BrokenPipeError, OSError) as exc:
            self._kill()
            raise ParserCrashed(f"{name} parser process unavailable: {exc}") from exc
        if not ready:
            self._kill()
            raise ParseTimeout(f"{name} parser exceeded {self.timeout_s:.0f}s")
        try:
            status, payload, result = self._conn.recv()
        except (EOFError, OSError) as exc:
            code = self._proc.exitcode if self._proc else None
            self._kill()
            raise ParserCrashed(f"{name} parser process died (exit code {code}); possibly out of memory") from exc
        if status == "ok":
            return payload, result
        if status == "parse_error":
            raise ParseError(payload)
        raise RuntimeError(payload)

    def _start(self) -> None:
        parent, child = self._ctx.Pipe()
        self._proc = self._ctx.Process(target=_child_main, args=(child,), daemon=True, name="ehelp-parser")
        self._proc.start()
        child.close()
        self._conn = parent

    def _kill(self) -> None:
        if self._proc is not None and self._proc.is_alive():
            self._proc.kill()
            self._proc.join(5)
        if self._conn is not None:
            self._conn.close()
        self._proc, self._conn = None, None

    def close(self) -> None:
        if self._conn is not None and self._proc is not None and self._proc.is_alive():
            try:
                self._conn.send(None)
                self._proc.join(5)
            except OSError:
                pass
        self._kill()
