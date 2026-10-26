"""A persisted query is stored only under the SHA-256 of its text.

The HTTP APQ path refuses a hash that does not match its query; the operator API
(``apq_store.store_persisted_query`` and the backends' ``store_persisted_query``)
refuses it too, so no text can be stored under the hash of another query.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from fraiseql.middleware.apq_caching import register_queries_from_directory
from fraiseql.storage import apq_store
from fraiseql.storage.apq_store import compute_query_hash
from fraiseql.storage.backends.memory import MemoryAPQBackend
from fraiseql.storage.backends.postgresql import PostgreSQLAPQBackend

_QUERY = "{ users { id } }"
_OTHER = "mutation { deleteEverything }"


@pytest.fixture(autouse=True)
def _clear_global_store() -> None:
    apq_store.clear_storage()
    yield
    apq_store.clear_storage()


def _pg_backend() -> PostgreSQLAPQBackend:
    return PostgreSQLAPQBackend({"auto_create_tables": False}, database_url="postgresql://x/y")


class TestGlobalStore:
    def test_a_hash_that_does_not_match_the_query_is_refused(self) -> None:
        with pytest.raises(ValueError, match="does not match"):
            apq_store.store_persisted_query(compute_query_hash(_QUERY), _OTHER)
        assert apq_store.get_persisted_query(compute_query_hash(_QUERY)) is None

    def test_the_matching_hash_is_stored(self) -> None:
        apq_store.store_persisted_query(compute_query_hash(_QUERY), _QUERY)
        assert apq_store.get_persisted_query(compute_query_hash(_QUERY)) == _QUERY


class TestMemoryBackend:
    def test_a_hash_that_does_not_match_the_query_is_refused(self) -> None:
        backend = MemoryAPQBackend()
        with pytest.raises(ValueError, match="does not match"):
            backend.store_persisted_query(compute_query_hash(_QUERY), _OTHER)
        assert backend.get_persisted_query(compute_query_hash(_QUERY)) is None

    def test_register_queries_still_stores_each_query(self) -> None:
        backend = MemoryAPQBackend()
        registered = backend.register_queries([_QUERY, _OTHER])
        assert registered == {compute_query_hash(q): q for q in (_QUERY, _OTHER)}
        assert backend.get_persisted_query(compute_query_hash(_OTHER)) == _OTHER

    def test_apq_queries_dir_still_loads(self, tmp_path: Path) -> None:
        (tmp_path / "users.graphql").write_text(_QUERY)
        backend = MemoryAPQBackend()
        register_queries_from_directory(backend, str(tmp_path))
        assert backend.get_persisted_query(compute_query_hash(_QUERY)) == _QUERY


class TestPostgreSQLBackend:
    def test_a_hash_that_does_not_match_the_query_is_refused(self) -> None:
        backend = _pg_backend()
        with (
            patch.object(PostgreSQLAPQBackend, "_execute_query") as execute,
            pytest.raises(ValueError, match="does not match"),
        ):
            backend.store_persisted_query(compute_query_hash(_QUERY), _OTHER)
        execute.assert_not_called()
        assert compute_query_hash(_QUERY) not in backend._query_text_cache

    def test_the_matching_hash_is_stored(self) -> None:
        backend = _pg_backend()
        with patch.object(PostgreSQLAPQBackend, "_execute_query") as execute:
            backend.store_persisted_query(compute_query_hash(_QUERY), _QUERY)
        execute.assert_called_once()
        assert execute.call_args.args[1] == (compute_query_hash(_QUERY), _QUERY)
