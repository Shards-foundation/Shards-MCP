"""Safe bootstrap-secret resolution for local and container deployments."""
from __future__ import annotations

import os
from pathlib import Path
import stat


def admin_token_from_environment() -> str:
    direct = os.getenv("SHARDS_ADMIN_TOKEN", "")
    filename = os.getenv("SHARDS_ADMIN_TOKEN_FILE", "")
    if direct and filename:
        raise ValueError("Configure only one of SHARDS_ADMIN_TOKEN or SHARDS_ADMIN_TOKEN_FILE")
    if filename:
        path = Path(filename).expanduser()
        if path.is_symlink():
            raise ValueError("admin token file must not be a symbolic link")
        descriptor = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("admin token must come from a regular file")
            if metadata.st_size > 4096:
                raise ValueError("admin token file exceeds maximum size")
            with os.fdopen(descriptor, "r", encoding="ascii") as stream:
                descriptor = -1
                token = stream.read(4097).strip()
        finally:
            if descriptor != -1:
                os.close(descriptor)
    else:
        token = direct
    if len(token) < 32 or len(set(token)) < 12:
        raise ValueError("bootstrap token must be >=32 characters with >=12 distinct characters")
    return token
