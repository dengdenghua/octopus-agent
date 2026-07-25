"""Workspace: first-class mount + membership entity for Octopus-Agent.

Public surface:
    Workspace            — data model for a single workspace
    WorkspaceMember      — data model for a membership row
    WorkspaceStore       — SQLite-backed persistence
    encrypt_options      — encrypt sensitive fields in mount_options dict
    decrypt_options      — inverse of encrypt_options

See ``model.py`` for the dataclasses, ``crypto.py`` for the at-rest
encryption scheme, and ``store.py`` for the SQLite store.
"""

from __future__ import annotations

from runtime.workspace.crypto import decrypt_options, encrypt_options
from runtime.workspace.model import (
    VALID_MEMBER_ROLES,
    VALID_MOUNT_TYPES,
    Workspace,
    WorkspaceMember,
)
from runtime.workspace.store import WorkspaceStore

__all__ = [
    "VALID_MEMBER_ROLES",
    "VALID_MOUNT_TYPES",
    "Workspace",
    "WorkspaceMember",
    "WorkspaceStore",
    "decrypt_options",
    "encrypt_options",
]
