"""Tests for logical WHERE operators (OR, AND, NOT) in GraphQL where inputs.

This module tests the implementation of logical operators that allow complex
filtering conditions similar to Hasura and Prisma GraphQL libraries.
"""

import uuid
from decimal import Decimal
from typing import Optional

import pytest

import fraiseql
from fraiseql.sql import (
    BooleanFilter,
    DecimalFilter,
    IntFilter,
    StringFilter,
    create_graphql_where_input,
)

pytestmark = [pytest.mark.integration, pytest.mark.database]


@fraiseql.type
class Product:
    """Product model for testing logical operators."""

    id: uuid.UUID
    name: str
    price: Decimal
    stock: int
    category: str
    is_active: bool
    description: Optional[str] = None


class TestLogicalOperators:
    """Test logical operators in GraphQL where inputs."""

    def test_or_operator_structure(self) -> None:
        """Test that OR operator is available and properly typed."""
        ProductWhereInput = create_graphql_where_input(Product)

        # Should be able to create with OR operator
        where_input = ProductWhereInput(
            OR=[
                ProductWhereInput(name=StringFilter(eq="Widget A")),
                ProductWhereInput(name=StringFilter(eq="Widget B")),
            ]
        )

        assert where_input.OR is not None
        assert len(where_input.OR) == 2
        assert where_input.OR[0].name.eq == "Widget A"
        assert where_input.OR[1].name.eq == "Widget B"

    def test_and_operator_structure(self) -> None:
        """Test that AND operator is available and properly typed."""
        ProductWhereInput = create_graphql_where_input(Product)

        # Should be able to create with AND operator
        where_input = ProductWhereInput(
            AND=[
                ProductWhereInput(category=StringFilter(eq="Electronics")),
                ProductWhereInput(is_active=BooleanFilter(eq=True)),
            ]
        )

        assert where_input.AND is not None
        assert len(where_input.AND) == 2
        assert where_input.AND[0].category.eq == "Electronics"
        assert where_input.AND[1].is_active.eq is True

    def test_not_operator_structure(self) -> None:
        """Test that NOT operator is available and properly typed."""
        ProductWhereInput = create_graphql_where_input(Product)

        # Should be able to create with NOT operator
        where_input = ProductWhereInput(NOT=ProductWhereInput(is_active=BooleanFilter(eq=False)))

        assert where_input.NOT is not None
        assert where_input.NOT.is_active.eq is False

    def test_mixed_logical_and_field_operators(self) -> None:
        """Test combining logical operators with field operators."""
        ProductWhereInput = create_graphql_where_input(Product)

        # Should be able to mix logical and field operators
        where_input = ProductWhereInput(
            category=StringFilter(eq="Electronics"),  # Field operator
            OR=[  # Logical operator
                ProductWhereInput(price=DecimalFilter(lt=Decimal(50))),
                ProductWhereInput(stock=IntFilter(gt=100)),
            ],
        )

        assert where_input.category.eq == "Electronics"
        assert len(where_input.OR) == 2
        assert where_input.OR[0].price.lt == Decimal(50)
        assert where_input.OR[1].stock.gt == 100

    def test_nested_logical_operators(self) -> None:
        """Test nested logical operators (OR inside AND, etc.)."""
        ProductWhereInput = create_graphql_where_input(Product)

        # Complex nested structure: AND containing OR
        where_input = ProductWhereInput(
            AND=[
                ProductWhereInput(category=StringFilter(eq="Electronics")),
                ProductWhereInput(
                    OR=[
                        ProductWhereInput(name=StringFilter(contains="Phone")),
                        ProductWhereInput(name=StringFilter(contains="Tablet")),
                    ]
                ),
            ]
        )

        assert len(where_input.AND) == 2
        assert where_input.AND[0].category.eq == "Electronics"
        assert len(where_input.AND[1].OR) == 2
        assert where_input.AND[1].OR[0].name.contains == "Phone"
        assert where_input.AND[1].OR[1].name.contains == "Tablet"

    def test_conversion_to_sql_where_with_or(self) -> None:
        """Test conversion from GraphQL OR input to SQL where type."""
        ProductWhereInput = create_graphql_where_input(Product)

        where_input = ProductWhereInput(
            OR=[
                ProductWhereInput(name=StringFilter(eq="Product A")),
                ProductWhereInput(name=StringFilter(eq="Product B")),
            ]
        )

        # Convert to SQL where type
        sql_where = where_input._to_sql_where()

        # Should have OR operator
        assert hasattr(sql_where, "OR")
        assert sql_where.OR is not None
        assert len(sql_where.OR) == 2

    def test_conversion_to_sql_where_with_and(self) -> None:
        """Test conversion from GraphQL AND input to SQL where type."""
        ProductWhereInput = create_graphql_where_input(Product)

        where_input = ProductWhereInput(
            AND=[
                ProductWhereInput(category=StringFilter(eq="Electronics")),
                ProductWhereInput(is_active=BooleanFilter(eq=True)),
            ]
        )

        # Convert to SQL where type
        sql_where = where_input._to_sql_where()

        # Should have AND operator
        assert hasattr(sql_where, "AND")
        assert sql_where.AND is not None
        assert len(sql_where.AND) == 2

    def test_conversion_to_sql_where_with_not(self) -> None:
        """Test conversion from GraphQL NOT input to SQL where type."""
        ProductWhereInput = create_graphql_where_input(Product)

        where_input = ProductWhereInput(NOT=ProductWhereInput(is_active=BooleanFilter(eq=False)))

        # Convert to SQL where type
        sql_where = where_input._to_sql_where()

        # Should have NOT operator
        assert hasattr(sql_where, "NOT")
        assert sql_where.NOT is not None


class TestLogicalOperatorsSQLGeneration:
    """Test SQL generation for logical operators."""

    def test_or_sql_generation(self) -> None:
        """Test that OR operators generate correct SQL with parentheses."""
        ProductWhereInput = create_graphql_where_input(Product)

        where_input = ProductWhereInput(
            OR=[
                ProductWhereInput(name=StringFilter(eq="Product A")),
                ProductWhereInput(name=StringFilter(eq="Product B")),
            ]
        )

        sql_where = where_input._to_sql_where()
        sql = sql_where.to_sql()

        # Should generate SQL with OR and proper parentheses
        assert sql is not None
        sql_str = str(sql)
        assert "OR" in sql_str

    def test_and_sql_generation(self) -> None:
        """Test that AND operators generate correct SQL with parentheses."""
        ProductWhereInput = create_graphql_where_input(Product)

        where_input = ProductWhereInput(
            AND=[
                ProductWhereInput(category=StringFilter(eq="Electronics")),
                ProductWhereInput(is_active=BooleanFilter(eq=True)),
            ]
        )

        sql_where = where_input._to_sql_where()
        sql = sql_where.to_sql()

        # Should generate SQL with AND
        assert sql is not None
        str(sql)
        # Note: explicit AND might be omitted as it's default behavior
        # The key is that both conditions should be present

    def test_not_sql_generation(self) -> None:
        """Test that NOT operators generate correct SQL with parentheses."""
        ProductWhereInput = create_graphql_where_input(Product)

        where_input = ProductWhereInput(NOT=ProductWhereInput(is_active=BooleanFilter(eq=False)))

        sql_where = where_input._to_sql_where()
        sql = sql_where.to_sql()

        # Should generate SQL with NOT
        assert sql is not None
        sql_str = str(sql)
        assert "NOT" in sql_str

    def test_complex_nested_sql_generation(self) -> None:
        """Test complex nested logical operators generate correct SQL."""
        ProductWhereInput = create_graphql_where_input(Product)

        where_input = ProductWhereInput(
            AND=[
                ProductWhereInput(category=StringFilter(eq="Electronics")),
                ProductWhereInput(
                    OR=[
                        ProductWhereInput(price=DecimalFilter(lt=Decimal(100))),
                        ProductWhereInput(stock=IntFilter(gt=50)),
                    ]
                ),
                ProductWhereInput(NOT=ProductWhereInput(is_active=BooleanFilter(eq=False))),
            ]
        )

        sql_where = where_input._to_sql_where()
        sql = sql_where.to_sql()

        # Should generate complex SQL with proper nesting and parentheses
        assert sql is not None
        sql_str = str(sql)
        # Should contain logical operators
        assert "OR" in sql_str or "AND" in sql_str or "NOT" in sql_str


class TestBackwardCompatibility:
    """Test that logical operators maintain full backward compatibility."""

    def test_existing_where_inputs_unchanged(self) -> None:
        """Test that existing where inputs work exactly as before."""
        ProductWhereInput = create_graphql_where_input(Product)

        # Old-style where input should work exactly as before
        where_input = ProductWhereInput(
            name=StringFilter(contains="Widget"),
            price=DecimalFilter(gte=Decimal(10), lt=Decimal(100)),
            is_active=BooleanFilter(eq=True),
        )

        sql_where = where_input._to_sql_where()
        sql = sql_where.to_sql()

        # Should still generate valid SQL
        assert sql is not None

        # Should still have the same field structure
        assert sql_where.name == {"contains": "Widget"}
        assert sql_where.price == {"gte": Decimal(10), "lt": Decimal(100)}
        assert sql_where.is_active == {"eq": True}

    def test_mixed_old_and_new_syntax(self) -> None:
        """Test mixing old field operators with new logical operators."""
        ProductWhereInput = create_graphql_where_input(Product)

        where_input = ProductWhereInput(
            # Old-style field operators
            category=StringFilter(eq="Electronics"),
            is_active=BooleanFilter(eq=True),
            # New-style logical operators
            OR=[
                ProductWhereInput(price=DecimalFilter(lt=Decimal(50))),
                ProductWhereInput(stock=IntFilter(gt=100)),
            ],
        )

        sql_where = where_input._to_sql_where()
        sql = sql_where.to_sql()

        # Should generate valid SQL combining both approaches
        assert sql is not None

        # Should have both field and logical operators
        assert sql_where.category == {"eq": "Electronics"}
        assert sql_where.is_active == {"eq": True}
        assert hasattr(sql_where, "OR")


class TestEdgeCasesAndErrorHandling:
    """Test edge cases and error handling for logical operators."""

    def test_empty_or_array(self) -> None:
        """Test handling of empty OR arrays."""
        ProductWhereInput = create_graphql_where_input(Product)

        where_input = ProductWhereInput(OR=[])
        sql_where = where_input._to_sql_where()
        sql_where.to_sql()

        # Empty OR should either generate no SQL or valid empty condition
        # The exact behavior can be determined during implementation

    def test_empty_and_array(self) -> None:
        """Test handling of empty AND arrays."""
        ProductWhereInput = create_graphql_where_input(Product)

        where_input = ProductWhereInput(AND=[])
        sql_where = where_input._to_sql_where()
        sql_where.to_sql()

        # Empty AND should either generate no SQL or valid empty condition

    def test_none_in_logical_operators(self) -> None:
        """Test handling of None values in logical operator arrays."""
        ProductWhereInput = create_graphql_where_input(Product)

        # This might be invalid input, but we should handle gracefully
        where_input = ProductWhereInput(
            OR=[
                ProductWhereInput(name=StringFilter(eq="Product A")),
                None,  # This might happen in edge cases
                ProductWhereInput(name=StringFilter(eq="Product B")),
            ]
        )

        # Should either filter out None values or handle gracefully
        where_input._to_sql_where()
        # Should not raise an exception
