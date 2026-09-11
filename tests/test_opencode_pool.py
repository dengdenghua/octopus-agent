import asyncio
from types import SimpleNamespace

from runtime.execution import opencode_backend as backend


def test_pool_reuses_isolated_roots_rotates_credentials_and_bounds_idle_processes(tmp_path, monkeypatch):
    starts, stops = [], []
    class Client:
        async def get(self, *args, **kwargs):
            return SimpleNamespace(status_code=200, json=lambda: {"healthy": True})
    async def start(*args, **kwargs):
        client = Client()
        starts.append(args)
        return SimpleNamespace(returncode=None, terminate=lambda: None), client
    async def stop(process, client):
        stops.append(client)
    async def validate(*args, **kwargs):
        pass
    monkeypatch.setattr(backend, "_start_server", start)
    monkeypatch.setattr(backend, "_stop_server", stop)
    monkeypatch.setattr(backend, "validate_catalog_model", validate)
    backend._warm_servers.clear()
    async def run():
        async def acquire(root, key=None):
            async with backend.managed_server("opencode", root, key, "big-pickle", False) as client:
                return client
        try:
            alice = await acquire(tmp_path / "alice")
            bob = await acquire(tmp_path / "bob")
            assert alice is not bob
            assert await acquire(tmp_path / "alice") is alice
            assert await acquire(tmp_path / "bob") is bob
            rotated = await acquire(tmp_path / "alice", "new-key")
            assert rotated is not alice
            assert alice in stops
            for n in range(6):
                await acquire(tmp_path / str(n))
                assert len(backend._warm_servers) <= 3
            # A failed turn is never returned to the reusable pool.
            try:
                async with backend.managed_server("opencode", tmp_path / "failure", None, "big-pickle", False):
                    raise RuntimeError("interrupted turn")
            except RuntimeError:
                pass
            assert not any(e.root == (tmp_path / "failure").resolve() for e in backend._warm_servers.values())
        finally:
            for entry in tuple(backend._warm_servers.values()):
                if entry.idle_handle:
                    entry.idle_handle.cancel()
                await stop(entry.process, entry.client)
            backend._warm_servers.clear()
    asyncio.run(run())
    assert len(stops) == len(starts)
