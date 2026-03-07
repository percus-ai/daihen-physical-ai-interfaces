import asyncio

import interfaces_backend.api.operate as operate_api
from interfaces_backend.models.operate import OperateStatusResponse


def test_get_operate_status_runs_collection_in_thread(monkeypatch):
    captured: dict[str, object] = {}

    def fake_collect():
        captured["collect_called"] = True
        return OperateStatusResponse(
            backend={"name": "backend", "status": "running", "message": "ok", "details": {}},
            vlabor={"name": "vlabor", "status": "running", "message": "ok", "details": {}},
            lerobot={"name": "lerobot", "status": "running", "message": "ok", "details": {}},
            network={"name": "network", "status": "running", "message": "ok", "details": {}},
            driver={"name": "driver", "status": "running", "message": "ok", "details": {}},
        )

    async def fake_to_thread(func, /, *args, **kwargs):
        captured["func"] = func
        captured["args"] = args
        captured["kwargs"] = kwargs
        return func(*args, **kwargs)

    monkeypatch.setattr(operate_api, "_collect_operate_status", fake_collect)
    monkeypatch.setattr(operate_api.asyncio, "to_thread", fake_to_thread)

    response = asyncio.run(operate_api.get_operate_status())

    assert isinstance(response, OperateStatusResponse)
    assert response.backend.status == "running"
    assert captured["func"] is fake_collect
    assert captured["args"] == ()
    assert captured["kwargs"] == {}
    assert captured["collect_called"] is True
