"""Reuse the autouse fixtures from the main test suite.

The fixtures in ``tests/conftest.py`` (module-state reset, gene-lock
isolation, etc.) are registered as plugins so tests under
``runtime/tests/`` get the same process-wide reset behavior.
"""

pytest_plugins = ("tests.conftest",)
