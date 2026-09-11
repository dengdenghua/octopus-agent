"""Integrity primitives: tamper-evident seals for append-only records."""

from runtime.platform.integrity.chain import GENESIS, seal_step, verify_chain

__all__ = ["GENESIS", "seal_step", "verify_chain"]
