"""Test vector operators for PostgreSQL pgvector (TDD Red Cycle).

These tests focus on SQL generation for pgvector's three native distance operators:
- <=> : cosine distance
- <-> : L2/Euclidean distance
- <#> : negative inner product
"""

import pytest
from psycopg.sql import SQL, Composed

from fraiseql.sql.where.core.field_detection import FieldType
from fraiseql.sql.where.operators import get_operator_function
from fraiseql.sql.where.operators.vectors import (
    build_cosine_distance_sql,
    build_custom_distance_sql,
    build_half_vector_avg_aggregation,
    build_half_vector_sum_aggregation,
    build_hamming_distance_sql,
    build_inner_product_sql,
    build_jaccard_distance_sql,
    build_l1_distance_sql,
    build_l2_distance_sql,
    build_quantization_reconstruct_sql,
    build_quantized_distance_sql,
    build_sparse_cosine_distance_sql,
    build_sparse_inner_product_sql,
    build_sparse_l2_distance_sql,
    build_sparse_vector_avg_aggregation,
    build_sparse_vector_sum_aggregation,
    build_vector_avg_aggregation,
    build_vector_norm_sql,
    build_vector_sum_aggregation,
)


class TestVectorOperators:
    """Test vector distance operator SQL generation."""

    def test_cosine_distance_sql(self) -> None:
        """Should generate cosine distance SQL using <=> operator."""
        # Red cycle - this will fail initially
        path_sql = SQL("embedding")
        value = [0.1, 0.2, 0.3]

        result = build_cosine_distance_sql(path_sql, value)

        # Should generate: (embedding)::vector <=> '[0.1,0.2,0.3]'::vector
        assert isinstance(result, Composed)
        sql_str = str(result)
        assert "<=>" in sql_str
        assert "'[0.1,0.2,0.3]'" in sql_str
        assert "::vector" in sql_str

    def test_l2_distance_sql(self) -> None:
        """Should generate L2 distance SQL using <-> operator."""
        # Red cycle - this will fail initially
        path_sql = SQL("text_embedding")
        value = [1.0, 2.0, 3.0, 4.0]

        result = build_l2_distance_sql(path_sql, value)

        # Should generate: (text_embedding)::vector <-> '[1.0,2.0,3.0,4.0]'::vector
        assert isinstance(result, Composed)
        sql_str = str(result)
        assert "<->" in sql_str
        assert "'[1.0,2.0,3.0,4.0]'" in sql_str
        assert "::vector" in sql_str

    def test_inner_product_sql(self) -> None:
        """Should generate inner product SQL using <#> operator."""
        # Red cycle - this will fail initially
        path_sql = SQL("image_embedding")
        value = [0.5, -0.1, 0.8]

        result = build_inner_product_sql(path_sql, value)

        # Should generate: (image_embedding)::vector <#> '[0.5,-0.1,0.8]'::vector
        assert isinstance(result, Composed)
        sql_str = str(result)
        assert "<#>" in sql_str
        assert "'[0.5,-0.1,0.8]'" in sql_str
        assert "::vector" in sql_str

    def test_l1_distance_sql(self) -> None:
        """Should generate L1/Manhattan distance SQL using <+> operator."""
        # Red cycle - this will fail initially
        path_sql = SQL("sparse_embedding")
        value = [0.1, -0.2, 0.3]

        result = build_l1_distance_sql(path_sql, value)

        # Should generate: (sparse_embedding)::vector <+> '[0.1,-0.2,0.3]'::vector
        assert isinstance(result, Composed)
        sql_str = str(result)
        assert "<+>" in sql_str
        assert "'[0.1,-0.2,0.3]'" in sql_str
        assert "::vector" in sql_str

    def test_hamming_distance_sql(self) -> None:
        """Should generate Hamming distance SQL using <~> operator for bit vectors."""
        # Red cycle - this will fail initially
        path_sql = SQL("fingerprint")
        value = "101010"  # 6-bit binary string

        result = build_hamming_distance_sql(path_sql, value)

        # Should generate: (fingerprint)::bit <~> '101010'::bit
        assert isinstance(result, Composed)
        sql_str = str(result)
        assert "<~>" in sql_str
        assert "'101010'" in sql_str
        assert "::bit" in sql_str

    def test_jaccard_distance_sql(self) -> None:
        """Should generate Jaccard distance SQL using <%> operator for bit vectors."""
        # Red cycle - this will fail initially
        path_sql = SQL("features")
        value = "111000"  # 6-bit binary string

        result = build_jaccard_distance_sql(path_sql, value)

        # Should generate: (features)::bit <%> '111000'::bit
        assert isinstance(result, Composed)
        sql_str = str(result)
        assert "<%>" in sql_str
        assert "'111000'" in sql_str
        assert "::bit" in sql_str

    def test_vector_casting_format(self) -> None:
        """Should properly format vector values as PostgreSQL array literals."""
        # Red cycle - this will fail initially
        path_sql = SQL("embedding")
        value = [0.123456, -0.789, 1.0]

        result = build_cosine_distance_sql(path_sql, value)

        # Should format as '[0.123456,-0.789,1.0]'::vector
        sql_str = str(result)
        assert "'[0.123456,-0.789,1.0]'" in sql_str

    def test_vector_null_handling(self) -> None:
        """Should handle NULL vectors appropriately."""
        # Red cycle - this will fail initially
        path_sql = SQL("embedding")
        value = [0.0, 0.0]

        result = build_cosine_distance_sql(path_sql, value)

        # NULL handling will be tested in integration, but basic structure should work
        assert isinstance(result, Composed)

    def test_vector_operators_registered(self) -> None:
        """Should have vector operators registered in OPERATOR_MAP."""
        # Test that get_operator_function returns correct builders for vector operators
        cosine_func = get_operator_function(FieldType.VECTOR, "cosine_distance")
        assert cosine_func == build_cosine_distance_sql

        l2_func = get_operator_function(FieldType.VECTOR, "l2_distance")
        assert l2_func == build_l2_distance_sql

        l1_func = get_operator_function(FieldType.VECTOR, "l1_distance")
        assert l1_func == build_l1_distance_sql

        inner_func = get_operator_function(FieldType.VECTOR, "inner_product")
        assert inner_func == build_inner_product_sql

        hamming_func = get_operator_function(FieldType.VECTOR, "hamming_distance")
        assert hamming_func == build_hamming_distance_sql

        jaccard_func = get_operator_function(FieldType.VECTOR, "jaccard_distance")
        assert jaccard_func == build_jaccard_distance_sql

    def test_get_operator_function_vector(self) -> None:
        """Should return correct builder functions for vector operators."""
        # Test that the functions work correctly when called through get_operator_function
        path_sql = SQL("embedding")
        value = [0.1, 0.2, 0.3]

        cosine_func = get_operator_function(FieldType.VECTOR, "cosine_distance")
        result = cosine_func(path_sql, value)
        assert isinstance(result, Composed)
        assert "<=>" in str(result)

    def test_vector_operator_function_signatures(self) -> None:
        """Should have correct function signatures for vector operators."""
        # Test that the functions can be called with expected parameters
        path_sql = SQL("test_column")
        test_vector = [1.0, 2.0, 3.0]

        # All three functions should work without errors
        cosine_result = build_cosine_distance_sql(path_sql, test_vector)
        l2_result = build_l2_distance_sql(path_sql, test_vector)
        inner_result = build_inner_product_sql(path_sql, test_vector)

        assert all(isinstance(r, Composed) for r in [cosine_result, l2_result, inner_result])


class TestDenseVectorDistanceOperators:
    """Test dense vector distance calculation operators."""

    def test_cosine_distance(self):
        """Test cosine distance operator."""
        path_sql = SQL("embedding")
        vector = [0.1, 0.2, 0.3, 0.4, 0.5]
        result = build_cosine_distance_sql(path_sql, vector)
        sql_str = result.as_string(None)
        assert "<=>" in sql_str
        assert "::vector" in sql_str
        assert "[0.1,0.2,0.3,0.4,0.5]" in sql_str
        assert "embedding" in sql_str

    def test_l2_distance(self):
        """Test L2/Euclidean distance operator."""
        path_sql = SQL("vector_field")
        vector = [1.0, 2.0, 3.0]
        result = build_l2_distance_sql(path_sql, vector)
        sql_str = result.as_string(None)
        assert "<->" in sql_str
        assert "::vector" in sql_str

    def test_inner_product(self):
        """Test inner product operator."""
        path_sql = SQL("embeddings")
        vector = [0.5, -0.2, 0.8]
        result = build_inner_product_sql(path_sql, vector)
        sql_str = result.as_string(None)
        assert "<#>" in sql_str
        assert "::vector" in sql_str
        assert "[0.5,-0.2,0.8]" in sql_str

    def test_l1_distance(self):
        """Test L1/Manhattan distance operator."""
        path_sql = SQL("vectors")
        vector = [1.5, 2.5, -1.0]
        result = build_l1_distance_sql(path_sql, vector)
        sql_str = result.as_string(None)
        assert "<+>" in sql_str
        assert "::vector" in sql_str
        assert "[1.5,2.5,-1.0]" in sql_str


class TestBinaryVectorDistanceOperators:
    """Test binary vector distance operators."""

    def test_hamming_distance(self):
        """Test Hamming distance for bit vectors."""
        path_sql = SQL("bit_vector")
        bit_string = "101010"
        result = build_hamming_distance_sql(path_sql, bit_string)
        sql_str = result.as_string(None)
        assert "<~>" in sql_str
        assert "::bit" in sql_str
        assert "101010" in sql_str

    def test_jaccard_distance(self):
        """Test Jaccard distance for bit vectors."""
        path_sql = SQL("bit_set")
        bit_string = "111000"
        result = build_jaccard_distance_sql(path_sql, bit_string)
        sql_str = result.as_string(None)
        assert "<%>" in sql_str
        assert "::bit" in sql_str
        assert "111000" in sql_str


class TestSparseVectorDistanceOperators:
    """Test sparse vector distance operators."""

    def test_sparse_cosine_distance(self):
        """Test sparse vector cosine distance."""
        path_sql = SQL("sparse_embedding")
        sparse_vector = {"indices": [0, 2, 4], "values": [0.1, 0.3, 0.5]}
        result = build_sparse_cosine_distance_sql(path_sql, sparse_vector)
        sql_str = result.as_string(None)
        assert "<=>" in sql_str
        assert "::sparsevec" in sql_str
        assert "0:0.1,2:0.3,4:0.5" in sql_str

    def test_sparse_l2_distance(self):
        """Test sparse vector L2 distance."""
        path_sql = SQL("sparse_vec")
        sparse_vector = {"indices": [1, 3, 5], "values": [0.2, 0.4, 0.6]}
        result = build_sparse_l2_distance_sql(path_sql, sparse_vector)
        sql_str = result.as_string(None)
        assert "<->" in sql_str
        assert "::sparsevec" in sql_str
        assert "1:0.2,3:0.4,5:0.6" in sql_str

    def test_sparse_inner_product(self):
        """Test sparse vector inner product."""
        path_sql = SQL("sparse_vectors")
        sparse_vector = {"indices": [0, 1, 2], "values": [1.0, 2.0, 3.0]}
        result = build_sparse_inner_product_sql(path_sql, sparse_vector)
        sql_str = result.as_string(None)
        assert "<#>" in sql_str
        assert "::sparsevec" in sql_str
        assert "0:1.0,1:2.0,2:3.0" in sql_str

    def test_sparse_empty_vector(self):
        """Test sparse vector with empty indices/values."""
        path_sql = SQL("sparse_field")
        sparse_vector = {"indices": [], "values": []}
        result = build_sparse_cosine_distance_sql(path_sql, sparse_vector)
        sql_str = result.as_string(None)
        assert "<=>" in sql_str
        assert "::sparsevec" in sql_str
        # Should handle empty case gracefully


class TestVectorAggregationOperators:
    """Test vector aggregation functions."""

    def test_vector_sum_aggregation(self):
        """Test vector SUM aggregation."""
        path_sql = SQL("embeddings")
        result = build_vector_sum_aggregation(path_sql)
        sql_str = result.as_string(None)
        assert "SUM(" in sql_str

    def test_vector_avg_aggregation(self):
        """Test vector AVG aggregation."""
        path_sql = SQL("embeddings")
        result = build_vector_avg_aggregation(path_sql)
        sql_str = result.as_string(None)
        assert "AVG(" in sql_str

    def test_vector_norm_sql(self):
        """Test vector norm calculation."""
        path_sql = SQL("embedding")
        result = build_vector_norm_sql(path_sql, None)
        sql_str = result.as_string(None)
        assert "vector_norm(" in sql_str or "l2_norm(" in sql_str


class TestSparseVectorAggregationOperators:
    """Test sparse vector aggregation functions."""

    def test_sparse_vector_sum_aggregation(self):
        """Test sparse vector SUM aggregation."""
        path_sql = SQL("sparse_embeddings")
        result = build_sparse_vector_sum_aggregation(path_sql)
        sql_str = result.as_string(None)
        assert "SUM(" in sql_str

    def test_sparse_vector_avg_aggregation(self):
        """Test sparse vector AVG aggregation."""
        path_sql = SQL("sparse_embeddings")
        result = build_sparse_vector_avg_aggregation(path_sql)
        sql_str = result.as_string(None)
        assert "AVG(" in sql_str


class TestHalfVectorAggregationOperators:
    """Test half vector (binary quantized) aggregation functions."""

    def test_half_vector_sum_aggregation(self):
        """Test half vector SUM aggregation."""
        path_sql = SQL("binary_embeddings")
        result = build_half_vector_sum_aggregation(path_sql)
        sql_str = result.as_string(None)
        assert "SUM(" in sql_str

    def test_half_vector_avg_aggregation(self):
        """Test half vector AVG aggregation."""
        path_sql = SQL("binary_embeddings")
        result = build_half_vector_avg_aggregation(path_sql)
        sql_str = result.as_string(None)
        assert "AVG(" in sql_str


class TestVectorQuantizationOperators:
    """Test vector quantization and reconstruction operators."""

    def test_quantized_distance_sql(self):
        """Test quantized vector distance."""
        path_sql = SQL("quantized_embedding")
        config = {"target_vector": [0.1, 0.2, 0.3], "distance_type": "cosine"}
        result = build_quantized_distance_sql(path_sql, config)
        sql_str = result.as_string(None)
        assert "quantized_cosine_distance(" in sql_str
        assert "::vector" in sql_str

    def test_quantization_reconstruct_sql(self):
        """Test quantization reconstruction."""
        path_sql = SQL("quantized_vector")
        result = build_quantization_reconstruct_sql(path_sql, None)
        sql_str = result.as_string(None)
        assert "reconstruct_quantized_vector(" in sql_str


class TestCustomVectorDistanceOperators:
    """Test custom vector distance operators."""

    def test_custom_distance_sql(self):
        """Test custom distance calculation."""
        path_sql = SQL("custom_vector")
        config = {"function": "my_distance_func", "parameters": [1.0, 2.0, 3.0]}
        result = build_custom_distance_sql(path_sql, config)
        sql_str = result.as_string(None)
        assert "my_distance_func(" in sql_str


class TestBinaryVectorBitWidth:
    """Both operands of a bit distance must carry the literal's width (#494).

    A bare ``::bit`` is ``bit(1)``. Casting *both* sides that way keeps the
    lengths in agreement, so PostgreSQL raises nothing and computes the distance
    over a single bit -- every row comes back 0. The existing assertions in
    ``TestBinaryVectorDistanceOperators`` only check ``"::bit" in sql_str``,
    which a ``bit(1)`` rendering satisfies, so they cannot see this.
    """

    QUERY_BITS = "1111000011110000111100001111000011110000111100001111000011110000"

    def test_hamming_casts_both_operands_to_the_literal_width(self) -> None:
        result = build_hamming_distance_sql(SQL('(data ->> \'fingerprint\')'), self.QUERY_BITS)
        assert result.as_string(None) == (
            "((data ->> 'fingerprint'))::bit(64) <~> "
            f"'{self.QUERY_BITS}'::bit(64)"
        )

    def test_jaccard_casts_both_operands_to_the_literal_width(self) -> None:
        result = build_jaccard_distance_sql(SQL('(data ->> \'fingerprint\')'), self.QUERY_BITS)
        assert result.as_string(None) == (
            "((data ->> 'fingerprint'))::bit(64) <%> "
            f"'{self.QUERY_BITS}'::bit(64)"
        )

    @pytest.mark.parametrize("builder", [build_hamming_distance_sql, build_jaccard_distance_sql])
    @pytest.mark.parametrize("width", [1, 6, 8, 64, 128])
    def test_width_tracks_the_literal_not_a_fixed_size(self, builder, width) -> None:
        bits = "10" * (width // 2) + "1" * (width % 2)
        assert len(bits) == width
        sql_str = builder(SQL("fingerprint"), bits).as_string(None)
        assert sql_str.count(f"::bit({width})") == 2
        # A bare ``::bit`` anywhere means an operand was left at bit(1).
        assert "::bit " not in sql_str
        assert not sql_str.endswith("::bit")

    @pytest.mark.parametrize("builder", [build_hamming_distance_sql, build_jaccard_distance_sql])
    def test_column_side_is_cast_too(self, builder) -> None:
        """The path is a JSONB text extraction, so it needs the cast as well."""
        sql_str = builder(SQL('(data ->> \'fp\')'), "101010").as_string(None)
        assert sql_str.startswith("((data ->> 'fp'))::bit(6)")
