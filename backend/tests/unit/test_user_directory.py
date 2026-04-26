import asyncio
from types import SimpleNamespace

from interfaces_backend.services import user_directory


def test_fetch_emails_runs_auth_requests_concurrently(monkeypatch):
    class _FakeAdmin:
        def __init__(self) -> None:
            self.active = 0
            self.max_active = 0

        async def get_user_by_id(self, user_id: str):
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0.01)
            self.active -= 1
            return SimpleNamespace(user=SimpleNamespace(email=f"{user_id}@example.test"))

    admin = _FakeAdmin()
    client = SimpleNamespace(auth=SimpleNamespace(admin=admin))

    async def _fake_get_service_client():
        return client

    monkeypatch.setattr(user_directory, "_get_service_client", _fake_get_service_client)

    emails = asyncio.run(user_directory._fetch_emails(["user-a", "user-b", "user-c"]))

    assert emails == {
        "user-a": "user-a@example.test",
        "user-b": "user-b@example.test",
        "user-c": "user-c@example.test",
    }
    assert admin.max_active > 1
