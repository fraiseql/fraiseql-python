"""Which keys CachedRepository invalidates, and that they match the keys find builds."""

import fnmatch
from unittest.mock import AsyncMock, MagicMock

import pytest

from fraiseql.caching import CachedRepository, ResultCache
from fraiseql.db import FraiseQLRepository


class RecordingBackend:
    def __init__(self) -> None:
        self.patterns: list[str] = []

    async def get(self, key: str) -> None:
        return None

    async def set(self, key: str, value: object, ttl: int) -> None:
        pass

    async def delete(self, key: str) -> bool:
        return False

    async def delete_pattern(self, pattern: str) -> int:
        self.patterns.append(pattern)
        return 0


def _repo(tenant_id: str | None = "t1") -> tuple[CachedRepository, RecordingBackend]:
    backend = RecordingBackend()
    context = {"tenant_id": tenant_id} if tenant_id else {}
    base = FraiseQLRepository(MagicMock(), context=context)
    base.execute_function = AsyncMock(return_value={})
    return CachedRepository(base, ResultCache(backend)), backend


def _matches(patterns: list[str], key: str) -> bool:
    return any(fnmatch.fnmatchcase(key, pattern) for pattern in patterns)


@pytest.mark.parametrize("tenant_id", ["t1", None])
@pytest.mark.parametrize("view", ["v_user", "app.v_user", "users", "tv_user"])
@pytest.mark.asyncio
async def test_function_invalidates_the_keys_find_builds(view: str, tenant_id: str | None) -> None:
    repo, backend = _repo(tenant_id)
    keys = [
        repo._build_key(view, "users", None, {}),
        repo._build_key(f"{view}:one", "user", None, {"where": {"id": {"eq": 1}}}),
    ]

    await repo.execute_function("app.fn_update_user", {"id": 1})

    for key in keys:
        assert _matches(backend.patterns, key), (key, backend.patterns)


@pytest.mark.asyncio
async def test_other_views_are_kept() -> None:
    repo, backend = _repo()
    key = repo._build_key("v_post", "posts", None, {})

    await repo.execute_function("fn_update_user", {"id": 1})

    assert not _matches(backend.patterns, key)


@pytest.mark.asyncio
async def test_multi_word_entity() -> None:
    repo, backend = _repo()
    keys = [repo._build_key(v, "f", None, {}) for v in ("v_blog_post", "v_post")]

    await repo.invalidate_for_function("fn_create_blog_post")

    assert all(_matches(backend.patterns, key) for key in keys)


@pytest.mark.asyncio
async def test_invalidate_view_for_one_tenant() -> None:
    repo, backend = _repo("t1")
    own = repo._build_key("app.v_user", "users", None, {})
    other_repo, _ = _repo("t2")
    other = other_repo._build_key("app.v_user", "users", None, {})

    await repo.invalidate_view("v_user", all_tenants=False)

    assert _matches(backend.patterns, own)
    assert not _matches(backend.patterns, other)
