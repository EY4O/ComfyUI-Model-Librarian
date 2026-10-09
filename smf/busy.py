"""One library-changing operation at a time.

Moving files (organize, undo, quarantine, dedupe) while a metadata fetch or
duplicate scan walks the same files can strand sidecars at old paths, so these
operations exclude each other. Nothing waits: a second operation is refused
with a message naming the one that's running. Downloads aren't affected
(they only create new files).
"""
from __future__ import annotations

import threading
from contextlib import contextmanager

_lock = threading.Lock()
_current: str | None = None


class Busy(Exception):
    pass


def current() -> str | None:
    return _current


def begin(name: str) -> None:
    global _current
    with _lock:
        if _current:
            raise Busy(f"{_current} is running — wait for it to finish (or stop it) first.")
        _current = name


def end(name: str) -> None:
    global _current
    with _lock:
        if _current == name:
            _current = None


@contextmanager
def operation(name: str):
    begin(name)
    try:
        yield
    finally:
        end(name)
