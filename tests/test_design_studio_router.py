from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.sensing.gateway import design_studio_router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(design_studio_router.create_design_studio_router())
    return TestClient(app)


def test_comfyui_rejects_non_local_service(monkeypatch) -> None:
    monkeypatch.setenv("OCTOPUS_COMFYUI_URL", "https://example.com")
    response = _client().get("/api/design/comfyui/status")
    assert response.status_code == 200
    assert response.json()["state"] == "invalid_config"


def test_comfyui_dependencies_inventory_is_read_only(monkeypatch, tmp_path) -> None:
    (tmp_path / "models" / "checkpoints").mkdir(parents=True)
    (tmp_path / "models" / "loras").mkdir(parents=True)
    (tmp_path / "models" / "checkpoints" / "base.safetensors").write_bytes(b"model")
    (tmp_path / "models" / "loras" / "style.ckpt").write_bytes(b"lora")
    (tmp_path / "models" / "loras" / "notes.txt").write_text("ignore")
    (tmp_path / "custom_nodes" / "ComfyUI-Manager").mkdir(parents=True)
    (tmp_path / "custom_nodes" / "_disabled").mkdir(parents=True)
    monkeypatch.setattr(design_studio_router, "_comfyui_home", lambda: tmp_path)

    response = _client().get("/api/design/comfyui/dependencies")
    assert response.status_code == 200
    payload = response.json()
    assert payload["detected"] is True
    assert payload["total_models"] == 2
    assert payload["model_counts"]["checkpoints"] == 1
    assert payload["model_counts"]["loras"] == 1
    assert payload["custom_nodes"] == ["ComfyUI-Manager"]
    assert payload["managed"] is False


def test_comfyui_workflow_import_and_list(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(design_studio_router, "_workflow_dir", lambda: tmp_path)
    client = _client()

    imported = client.post(
        "/api/design/comfyui/workflows/import",
        json={"name": "角色分镜", "workflow": {"1": {"class_type": "CheckpointLoaderSimple"}}},
    )
    assert imported.status_code == 200
    assert imported.json()["ok"] is True

    listed = client.get("/api/design/comfyui/workflows")
    assert listed.status_code == 200
    items = listed.json()["items"]
    imported_item = next(item for item in items if item["id"] == "角色分镜")
    assert imported_item["name"] == "角色分镜"
    assert imported_item["source"] == "user"

    detail = client.get("/api/design/comfyui/workflows/text-to-image")
    assert detail.status_code == 200
    assert detail.json()["source"] == "bundled"
    assert detail.json()["workflow"]["5"]["class_type"] == "KSampler"


def test_comfyui_workflow_save_persists_ui_and_rejects_stale_revision(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(design_studio_router, "_workflow_dir", lambda: tmp_path)
    client = _client()
    body = {
        "name": "产品图工作流",
        "workflow": {
            "1": {
                "class_type": "KSampler",
                "inputs": {"seed": 42, "steps": 24},
            }
        },
        "ui": {"positions": {"1": {"x": 160, "y": 220}}},
        "expected_revision": 0,
    }

    saved = client.put("/api/design/comfyui/workflows/product-shot", json=body)
    assert saved.status_code == 200
    assert saved.json()["revision"] == 1

    loaded = client.get("/api/design/comfyui/workflows/product-shot")
    assert loaded.status_code == 200
    assert loaded.json()["source"] == "user"
    assert loaded.json()["ui"]["positions"]["1"] == {"x": 160, "y": 220}
    assert loaded.json()["workflow"]["1"]["inputs"]["seed"] == 42

    stale = client.put("/api/design/comfyui/workflows/product-shot", json=body)
    assert stale.status_code == 409
    assert stale.json()["detail"] == {
        "code": "WORKFLOW_REVISION_CONFLICT",
        "revision": 1,
    }


def test_comfyui_object_info_returns_compact_local_node_specs(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "KSampler": {
                    "display_name": "KSampler 采样器",
                    "category": "sampling",
                    "input": {
                        "required": {
                            "seed": ["INT", {"default": 0}],
                            "sampler_name": [["euler", "dpmpp_2m"]],
                        },
                        "optional": {"control_after_generate": ["BOOLEAN"]},
                    },
                }
            }

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url):
            assert url == "http://127.0.0.1:8188/object_info"
            return FakeResponse()

    monkeypatch.setattr(design_studio_router.httpx, "AsyncClient", FakeAsyncClient)
    response = _client().get("/api/design/comfyui/object-info")
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["class_type"] == "KSampler"
    assert item["title"] == "KSampler 采样器"
    assert item["inputs"][0]["default"] == 0
    assert item["inputs"][2]["optional"] is True


def test_comfyui_queue_accepts_workflow_id_and_exposes_outputs(monkeypatch, tmp_path) -> None:
    workflow = {
        "name": "测试工作流",
        "workflow": {"1": {"class_type": "KSampler", "inputs": {}}},
    }
    (tmp_path / "workflow-one.json").write_text(json.dumps(workflow), encoding="utf-8")
    monkeypatch.setattr(design_studio_router, "_workflow_dir", lambda: tmp_path)

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, json):
            assert json["prompt"]["1"]["class_type"] == "KSampler"
            return FakeResponse({"prompt_id": "prompt-1"})

        async def get(self, _url):
            return FakeResponse(
                {
                    "prompt-1": {
                        "status": {"completed": True},
                        "outputs": {
                            "9": {
                                "images": [
                                    {
                                        "filename": "result.png",
                                        "subfolder": "final",
                                        "type": "output",
                                    }
                                ]
                            }
                        },
                    }
                }
            )

    monkeypatch.setattr(design_studio_router.httpx, "AsyncClient", FakeAsyncClient)
    client = _client()
    queued = client.post("/api/design/comfyui/queue", json={"workflow_id": "workflow-one"})
    assert queued.status_code == 200
    assert queued.json()["prompt_id"] == "prompt-1"

    result = client.get("/api/design/comfyui/history/prompt-1")
    assert result.status_code == 200
    assert result.json()["state"] == "completed"
    assert result.json()["outputs"][0]["filename"] == "result.png"
    assert "filename=result.png" in result.json()["outputs"][0]["url"]


def test_project_canvas_is_revisioned_and_persistent(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(design_studio_router, "_canvas_dir", lambda: tmp_path)
    client = _client()

    empty = client.get("/api/design/projects/project-1/canvas")
    assert empty.status_code == 200
    assert empty.json()["revision"] == 0
    assert empty.json()["document"] is None

    saved = client.put(
        "/api/design/projects/project-1/canvas",
        json={
            "expected_revision": 0,
            "document": {"title": "发布会画布", "nodes": [], "edges": []},
        },
    )
    assert saved.status_code == 200
    assert saved.json()["revision"] == 1

    loaded = client.get("/api/design/projects/project-1/canvas")
    assert loaded.json()["document"]["title"] == "发布会画布"

    conflict = client.put(
        "/api/design/projects/project-1/canvas",
        json={"expected_revision": 0, "document": {"title": "旧版本"}},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "CANVAS_REVISION_CONFLICT"


def test_project_canvas_rejects_unsafe_project_id(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(design_studio_router, "_canvas_dir", lambda: tmp_path)
    response = _client().get("/api/design/projects/..%2Fprivate/canvas")
    assert response.status_code == 404
