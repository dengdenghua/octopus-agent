"""runtime.memory.threads · octopus-agent thread store.

Wire format uses ``messages[] + additional_kwargs`` for interop with
client SDKs that expect that shape.
"""

from .session_index import IndexEntry, SessionIndex, entry_from_thread
from .store import ThreadStateStore

__all__ = [
    "IndexEntry",
    "SessionIndex",
    "ThreadStateStore",
    "entry_from_thread",
]
