"""Atomic filesystem write helpers for generated Bots Without Labels artefacts."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TextIO


@contextmanager
def atomic_text_writer(path: Path) -> Iterator[TextIO]:
    """Write text to a temporary sibling before replacing the target path.

    Args:
        path: Final output path to replace.

    Yields:
        Writable text handle for the temporary file.

    Raises:
        OSError: If the temporary file cannot be written or replaced.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
            yield handle
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        raise


@contextmanager
def atomic_path_writer(path: Path, mode: str) -> Iterator[Path]:
    """Reserve a temporary sibling path before replacing the target path.

    Use this helper when a library needs to receive a filesystem path rather
    than an open file handle.

    Args:
        path: Final output path to replace.
        mode: Mode used to create and immediately close the temporary file,
            such as "wb". The yielded value is a path, not an open handle; the
            caller is responsible for opening or writing that path before the
            context exits.

    Yields:
        Temporary sibling path that will replace the final path on success.

    Raises:
        OSError: If the temporary file cannot be created or replaced.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode,
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
        yield tmp_path
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        raise
