"""Shared SSH algorithm policy for optional Paramiko transports."""

from __future__ import annotations


def paramiko_disabled_algorithms() -> dict[str, list[str]]:
    """Disable the legacy RSA/SHA-1 signature algorithm.

    Paramiko 4.0.0 still advertises ``ssh-rsa`` even though modern RSA
    SHA-2 algorithms are available. Returning a fresh mapping avoids callers
    sharing mutable policy state with Paramiko.
    """
    return {"keys": ["ssh-rsa"], "pubkeys": ["ssh-rsa"]}


__all__ = ["paramiko_disabled_algorithms"]
