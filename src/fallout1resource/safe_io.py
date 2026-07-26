"""Atomic writes constrained by callers to the local workspace."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def write_file_atomic(target: Path, data: bytes, *, overwrite: bool) -> None:
    """Write bytes atomically, refusing an existing target unless requested."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if overwrite:
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=target.parent,
                prefix=f".{target.name}.",
                delete=False,
            ) as stream:
                temporary_name = stream.name
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, target)
        finally:
            if temporary_name is not None:
                Path(temporary_name).unlink(missing_ok=True)
        return

    created = False
    try:
        with target.open("xb") as stream:
            created = True
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        if created:
            target.unlink(missing_ok=True)
        raise
