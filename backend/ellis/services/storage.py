"""File storage for uploads and generated packets: local disk (dev, tests) or a private Supabase Storage bucket.

storage_path columns hold a key like "<case_id>/<doc_id>.png"; only this module knows where the bytes live.
The bucket is private and reached only with the server-side secret key; browsers download through the Case API.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import httpx

from ..config import settings

_bucket_ready = False
_bucket_lock = threading.Lock()


class StorageError(RuntimeError):
    pass


def _supabase() -> bool:
    return settings.storage_backend == "supabase"


def _local_path(key: str) -> Path:
    p = Path(key)
    return p if p.is_absolute() else settings.files_dir / key  # absolute: rows written before keys existed


def _api(path: str) -> str:
    return f"{settings.supabase_url.rstrip('/')}/storage/v1/{path}"


def _headers(**extra: str) -> dict[str, str]:
    k = settings.supabase_secret_key
    return {"Authorization": f"Bearer {k}", "apikey": k, **extra}


def _check(r: httpx.Response, what: str) -> httpx.Response:
    if r.status_code >= 300:
        raise StorageError(f"storage {what} failed: {r.status_code} {r.text[:200]}")
    return r


def _ensure_bucket() -> None:
    global _bucket_ready
    if _bucket_ready:
        return
    with _bucket_lock:
        if _bucket_ready:
            return
        b = settings.supabase_bucket
        r = httpx.get(_api(f"bucket/{b}"), headers=_headers(), timeout=20)
        if r.status_code == 200:
            if r.json().get("public"):
                raise StorageError(f"bucket {b} is public; case files need a private bucket")
        else:
            _check(httpx.post(_api("bucket"), headers=_headers(), timeout=20,
                              json={"id": b, "name": b, "public": False}), "create bucket")
        _bucket_ready = True


def put(key: str, data: bytes, mime: str) -> None:
    if not _supabase():
        p = _local_path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return
    _ensure_bucket()
    _check(httpx.post(_api(f"object/{settings.supabase_bucket}/{key}"), content=data, timeout=60,
                      headers=_headers(**{"Content-Type": mime, "x-upsert": "true"})), "upload")


def get(key: str) -> bytes:
    if not _supabase():
        return _local_path(key).read_bytes()
    _ensure_bucket()
    return _check(httpx.get(_api(f"object/{settings.supabase_bucket}/{key}"), headers=_headers(), timeout=60),
                  "download").content


@contextmanager
def local_file(key: str) -> Iterator[str]:
    """A filesystem path holding the object, for code that needs a path (the extraction subprocess)."""
    if not _supabase():
        yield str(_local_path(key))
        return
    fd, tmp = tempfile.mkstemp(suffix=Path(key).suffix, prefix="ellis-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(get(key))
        yield tmp
    finally:
        os.unlink(tmp)


def clear() -> None:
    """Delete every stored file (seed reset only)."""
    if not _supabase():
        shutil.rmtree(settings.files_dir, ignore_errors=True)
        return
    _ensure_bucket()
    b = settings.supabase_bucket
    keys: list[str] = []

    def walk(prefix: str) -> None:
        offset = 0
        while True:
            r = _check(httpx.post(_api(f"object/list/{b}"), headers=_headers(), timeout=30,
                                  json={"prefix": prefix, "limit": 1000, "offset": offset}), "list")
            items = r.json()
            for it in items:
                name = f"{prefix}{it['name']}"
                if it.get("id") is None:  # a folder
                    walk(name + "/")
                else:
                    keys.append(name)
            if len(items) < 1000:
                return
            offset += 1000

    walk("")
    for i in range(0, len(keys), 1000):
        _check(httpx.request("DELETE", _api(f"object/{b}"), headers=_headers(), timeout=60,
                             json={"prefixes": keys[i:i + 1000]}), "delete")
