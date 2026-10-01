from __future__ import annotations

from typing import NotRequired, TypedDict


class ArchivedSite(TypedDict):
    name: str
    size_bytes: int
    created_at: float
    backup_count: int
    timestamp: str | None


class RestorePayload(TypedDict):
    target_name: str
    admin_password: str
    include_public_files: NotRequired[bool]
    include_private_files: NotRequired[bool]
    files: NotRequired[list[str]]
