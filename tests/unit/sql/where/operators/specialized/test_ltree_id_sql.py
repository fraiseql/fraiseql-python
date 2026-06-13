"""Tests for LTree ID-based hierarchy SQL generation (Phase 2).

Tests for:
- _resolve_entity_name: _id suffix stripping
- _build_hierarchy_subquery: nested IN subquery SQL structure
- build_where_clause: entity_schema threading + interception
- Error handling: missing entity_schema, non-_id fields
- camelCase→snake_case conversion for operator names
"""

import pytest
from psycopg.sql import SQL

from fraiseql.sql.where.core.sql_builder import (
    _camel_to_snake,
    build_where_clause,
    build_where_clause_graphql,
)

# ============================================================================
# Cycle 1: _resolve_entity_name
# ============================================================================


class TestResolveEntityName:
    """Test entity name derivation from _id field names."""

    def _fn(self, name: str) -> str:
        from fraiseql.sql.where.core.sql_builder import _resolve_entity_name

        return _resolve_entity_name(name)

    def test_location_id(self) -> None:
        assert self._fn("location_id") == "location"

    def test_department_id(self) -> None:
        assert self._fn("department_id") == "department"

    def test_category_id(self) -> None:
        assert self._fn("category_id") == "category"

    def test_no_id_suffix_raises(self) -> None:
        with pytest.raises(ValueError, match="must end with '_id'"):
            self._fn("location_path")

    def test_plain_field_raises(self) -> None:
        with pytest.raises(ValueError, match="must end with '_id'"):
            self._fn("status")

    def test_just_id_raises(self) -> None:
        """'id' alone — no underscore prefix, so caught by the _id suffix check."""
        with pytest.raises(ValueError, match="must end with '_id'"):
            self._fn("id")

    def test_underscore_id_alone_raises(self) -> None:
        """'_id' alone produces an empty entity name after stripping."""
        with pytest.raises(ValueError, match="entity name is empty"):
            self._fn("_id")


# ============================================================================
# Cycle 2: _build_hierarchy_subquery
# ============================================================================


class TestBuildHierarchySubquery:
    """Test the nested IN subquery SQL generation."""

    def _fn(self, schema: str, entity: str, uuid: str, op: str) -> str:
        from fraiseql.sql.where.core.sql_builder import _build_hierarchy_subquery

        jsonb_path = SQL("data ->> 'location_id'")
        result = _build_hierarchy_subquery(schema, entity, uuid, op, jsonb_path)
        return result.as_string(None)

    def test_descendant_uses_in_pattern(self) -> None:
        sql = self._fn("tenant", "location", "abc-123", "<@")
        assert " IN " in sql

    def test_descendant_schema_is_quoted(self) -> None:
        sql = self._fn("tenant", "location", "abc-123", "<@")
        assert '"tenant"' in sql

    def test_descendant_table_is_quoted(self) -> None:
        sql = self._fn("tenant", "location", "abc-123", "<@")
        assert '"tb_location"' in sql

    def test_descendant_uuid_cast(self) -> None:
        sql = self._fn("tenant", "location", "abc-123", "<@")
        assert "::uuid" in sql

    def test_descendant_ltree_cast(self) -> None:
        sql = self._fn("tenant", "location", "abc-123", "<@")
        assert "::ltree" in sql

    def test_descendant_uses_ltree_op(self) -> None:
        sql = self._fn("tenant", "location", "abc-123", "<@")
        assert "<@" in sql

    def test_ancestor_uses_right_op(self) -> None:
        sql = self._fn("tenant", "location", "abc-123", "@>")
        assert "@>" in sql
        assert " IN " in sql

    def test_jsonb_value_cast_to_uuid(self) -> None:
        """JSONB ->> returns text; cast to ::uuid for type-correct UUID comparison."""
        sql = self._fn("tenant", "location", "abc-123", "<@")
        assert "::uuid" in sql
        # The left-hand side (JSONB field) is cast, not the subquery id column
        assert "::text" not in sql

    def test_uuid_value_included(self) -> None:
        sql = self._fn("tenant", "location", "abc-123", "<@")
        assert "abc-123" in sql


# ============================================================================
# Cycle 3 & 4: build_where_clause with entity_schema
# ============================================================================


class TestBuildWhereClauseDescendantOfId:
    """Test full WHERE clause generation for descendant_of_id."""

    def test_descendant_of_id_generates_in_subquery(self) -> None:
        where = {"location_id": {"descendant_of_id": "floor-uuid"}}
        result = build_where_clause(where, entity_schema="tenant")
        sql = result.as_string(None)
        assert " IN " in sql

    def test_descendant_of_id_schema_in_sql(self) -> None:
        where = {"location_id": {"descendant_of_id": "floor-uuid"}}
        result = build_where_clause(where, entity_schema="tenant")
        sql = result.as_string(None)
        assert '"tenant"' in sql

    def test_descendant_of_id_table_in_sql(self) -> None:
        where = {"location_id": {"descendant_of_id": "floor-uuid"}}
        result = build_where_clause(where, entity_schema="tenant")
        sql = result.as_string(None)
        assert '"tb_location"' in sql

    def test_descendant_of_id_uses_ltree_descendant_op(self) -> None:
        where = {"location_id": {"descendant_of_id": "floor-uuid"}}
        result = build_where_clause(where, entity_schema="tenant")
        sql = result.as_string(None)
        assert "<@" in sql

    def test_descendant_of_id_field_in_sql(self) -> None:
        where = {"location_id": {"descendant_of_id": "floor-uuid"}}
        result = build_where_clause(where, entity_schema="tenant")
        sql = result.as_string(None)
        assert "location_id" in sql


class TestBuildWhereClauseAncestorOfId:
    """Test full WHERE clause generation for ancestor_of_id."""

    def test_ancestor_of_id_generates_in_subquery(self) -> None:
        where = {"location_id": {"ancestor_of_id": "room-uuid"}}
        result = build_where_clause(where, entity_schema="tenant")
        sql = result.as_string(None)
        assert " IN " in sql

    def test_ancestor_of_id_uses_ltree_ancestor_op(self) -> None:
        where = {"location_id": {"ancestor_of_id": "room-uuid"}}
        result = build_where_clause(where, entity_schema="tenant")
        sql = result.as_string(None)
        assert "@>" in sql

    def test_ancestor_of_id_no_descendant_op(self) -> None:
        where = {"location_id": {"ancestor_of_id": "room-uuid"}}
        result = build_where_clause(where, entity_schema="tenant")
        sql = result.as_string(None)
        assert "<@" not in sql


# ============================================================================
# Cycle 5: Error handling
# ============================================================================


class TestErrorHandling:
    """Test error handling for missing entity_schema and non-_id fields."""

    def test_missing_entity_schema_raises(self) -> None:
        where = {"location_id": {"descendant_of_id": "some-uuid"}}
        with pytest.raises(ValueError, match="entity_schema"):
            build_where_clause(where)

    def test_missing_entity_schema_ancestor_raises(self) -> None:
        where = {"location_id": {"ancestor_of_id": "some-uuid"}}
        with pytest.raises(ValueError, match="entity_schema"):
            build_where_clause(where)

    def test_non_id_field_raises(self) -> None:
        """Using descendant_of_id on a non-_id field should raise ValueError."""
        where = {"status": {"descendant_of_id": "some-uuid"}}
        with pytest.raises(ValueError, match="must end with '_id'"):
            build_where_clause(where, entity_schema="tenant")

    def test_none_value_skipped(self) -> None:
        """descendant_of_id: None should be skipped (no condition generated)."""
        where = {"location_id": {"descendant_of_id": None}}
        result = build_where_clause(where)
        assert result.as_string(None) == "TRUE"

    def test_combined_with_eq(self) -> None:
        """Can combine descendant_of_id with other operators on the same field."""
        where = {"location_id": {"descendant_of_id": "some-uuid", "eq": "another-uuid"}}
        result = build_where_clause(where, entity_schema="tenant")
        sql = result.as_string(None)
        assert " IN " in sql
        assert "=" in sql


# ============================================================================
# Cycle 6: camelCase conversion
# ============================================================================


class TestCamelCaseConversion:
    """Verify camelCase→snake_case conversion for new operator names."""

    def test_descendant_of_id_conversion(self) -> None:
        assert _camel_to_snake("descendantOfId") == "descendant_of_id"

    def test_ancestor_of_id_conversion(self) -> None:
        assert _camel_to_snake("ancestorOfId") == "ancestor_of_id"

    def test_location_id_conversion(self) -> None:
        assert _camel_to_snake("locationId") == "location_id"

    def test_graphql_style_where_descendant(self) -> None:
        """GraphQL camelCase input should work end-to-end."""
        where = {"locationId": {"descendantOfId": "floor-uuid"}}
        result = build_where_clause(where, entity_schema="tenant")
        sql = result.as_string(None)
        assert " IN " in sql
        assert '"tb_location"' in sql

    def test_graphql_style_where_ancestor(self) -> None:
        """GraphQL camelCase input should work end-to-end."""
        where = {"locationId": {"ancestorOfId": "room-uuid"}}
        result = build_where_clause(where, entity_schema="tenant")
        sql = result.as_string(None)
        assert " IN " in sql
        assert "@>" in sql


# ============================================================================
# Cycle 6b: build_where_clause_graphql also accepts entity_schema
# ============================================================================


class TestBuildWhereClauseGraphql:
    """Test that build_where_clause_graphql also threads entity_schema."""

    def test_graphql_variant_descendant(self) -> None:
        where = {"locationId": {"descendantOfId": "floor-uuid"}}
        result = build_where_clause_graphql(where, entity_schema="tenant")
        assert result is not None
        sql = result.as_string(None)
        assert " IN " in sql
        assert '"tb_location"' in sql


# ============================================================================
# Cycle 7: Regression — existing ltree path operators unchanged
# ============================================================================


class TestRegressionExistingLtreeOperators:
    """Existing path-based ltree operators must still work without entity_schema."""

    def test_descendant_of_still_works(self) -> None:
        where = {"location_path": {"descendant_of": "root.floor1"}}
        result = build_where_clause(where)
        sql = result.as_string(None)
        assert "<@" in sql
        assert "root.floor1" in sql
        assert " IN " not in sql

    def test_ancestor_of_still_works(self) -> None:
        where = {"location_path": {"ancestor_of": "root.floor1.room2"}}
        result = build_where_clause(where)
        sql = result.as_string(None)
        assert "@>" in sql
        assert " IN " not in sql


# ============================================================================
# Cycle 8: FraiseQLConfig.default_entity_schema
# ============================================================================


class TestFraiseQLConfigEntitySchema:
    """Test that FraiseQLConfig accepts default_entity_schema."""

    def test_config_accepts_default_entity_schema(self) -> None:
        from fraiseql.fastapi.config import FraiseQLConfig

        config = FraiseQLConfig(
            database_url="postgresql://user:pass@localhost/mydb",
            default_entity_schema="tenant",
        )
        assert config.default_entity_schema == "tenant"

    def test_config_default_entity_schema_is_none_by_default(self) -> None:
        from fraiseql.fastapi.config import FraiseQLConfig

        config = FraiseQLConfig(
            database_url="postgresql://user:pass@localhost/mydb",
        )
        assert config.default_entity_schema is None


# ============================================================================
# Cycle 9: sql_column branch — native UUID column support
# ============================================================================


class TestDescendantOfIdNativeColumn:
    """descendant_of_id on a table_columns (native UUID) field."""

    def test_descendant_of_id_uses_native_column(self) -> None:
        from unittest.mock import MagicMock, patch

        from fraiseql.where_clause import FieldCondition

        condition = FieldCondition(
            field_path=["location_id"],
            operator="descendant_of_id",
            value="floor-uuid",
            lookup_strategy="sql_column",
            target_column="location_id",
        )
        mock_registry = MagicMock()
        mock_registry.config.default_entity_schema = "myschema"
        with patch(
            "fraiseql.gql.builders.registry.SchemaRegistry.get_instance",
            return_value=mock_registry,
        ):
            sql, _params = condition.to_sql()

        rendered = sql.as_string(None)
        assert '"location_id"' in rendered
        assert "data->>" not in rendered
        assert "tb_location" in rendered
        assert "<@" in rendered
        assert "floor-uuid" in rendered

    def test_ancestor_of_id_uses_native_column(self) -> None:
        from unittest.mock import MagicMock, patch

        from fraiseql.where_clause import FieldCondition

        condition = FieldCondition(
            field_path=["location_id"],
            operator="ancestor_of_id",
            value="room-uuid",
            lookup_strategy="sql_column",
            target_column="location_id",
        )
        mock_registry = MagicMock()
        mock_registry.config.default_entity_schema = "myschema"
        with patch(
            "fraiseql.gql.builders.registry.SchemaRegistry.get_instance",
            return_value=mock_registry,
        ):
            sql, _params = condition.to_sql()

        rendered = sql.as_string(None)
        assert '"location_id"' in rendered
        assert "data->>" not in rendered
        assert "@>" in rendered

    def test_missing_entity_schema_raises(self) -> None:
        from unittest.mock import MagicMock, patch

        from fraiseql.where_clause import FieldCondition

        condition = FieldCondition(
            field_path=["location_id"],
            operator="descendant_of_id",
            value="some-uuid",
            lookup_strategy="sql_column",
            target_column="location_id",
        )
        mock_registry = MagicMock()
        mock_registry.config.default_entity_schema = None
        with patch(
            "fraiseql.gql.builders.registry.SchemaRegistry.get_instance",
            return_value=mock_registry,
        ), pytest.raises(ValueError, match="default_entity_schema"):
            condition.to_sql()
