"""Document bytes stay behind this boundary. Domain code does not open storage paths."""

from __future__ import annotations

import hashlib
from pathlib import Path


class StorageProvider:
    def save(self, key: str, data: bytes, content_type: str | None = None) -> dict:
        raise NotImplementedError

    def read(self, key: str) -> bytes:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError

    def exists(self, key: str) -> bool:
        raise NotImplementedError

    def metadata(self, key: str) -> dict:
        raise NotImplementedError


class LocalStorageProvider(StorageProvider):
    def __init__(self, root: Path):
        self.root = Path(root)

    def save(self, key: str, data: bytes, content_type: str | None = None) -> dict:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return self.metadata(key, content_type=content_type, checksum=hashlib.sha256(data).hexdigest())

    def read(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise FileNotFoundError(key)
        return path.read_bytes()

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.is_file():
            path.unlink()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def metadata(self, key: str, content_type: str | None = None, checksum: str | None = None) -> dict:
        path = self._path(key)
        if not path.is_file():
            raise FileNotFoundError(key)
        stat = path.stat()
        body = path.read_bytes() if checksum is None else None
        return {
            "key": key,
            "size": stat.st_size,
            "content_type": content_type,
            "checksum": checksum or hashlib.sha256(body or b"").hexdigest(),
        }

    def _path(self, key: str) -> Path:
        if not key or "\\" in key or key.startswith("/"):
            raise ValueError("Invalid storage key")
        parts = Path(key).parts
        if not parts or any(part in {"", ".", ".."} for part in parts):
            raise ValueError("Invalid storage key")
        root = self.root.resolve()
        path = (root / key).resolve()
        if path != root and root not in path.parents:
            raise ValueError("Invalid storage key")
        return path


def get_storage() -> StorageProvider:
    from .db import DOCUMENTS

    DOCUMENTS.mkdir(parents=True, exist_ok=True)
    return LocalStorageProvider(DOCUMENTS)
