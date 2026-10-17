import pytest

"""Tests for GraphQL selection filter utilities."""

from unittest.mock import MagicMock

from graphql import FieldNode, NameNode, SelectionSetNode

from fraiseql.mutations.selection_filter import filter_mutation_result

pytestmark = pytest.mark.integration


def create_field_node_mock(name, alias=None, selections=None) -> FieldNode:
    """Create a FieldNode."""
    return FieldNode(
        name=NameNode(value=name),
        alias=NameNode(value=alias) if alias else None,
        selection_set=None
        if selections is None
        else SelectionSetNode(selections=tuple(selections)),
    )


@pytest.mark.unit
class TestSelectionFilter:
    """Test selection filter functionality."""

    def test_filter_mutation_result_simple_fields(self) -> None:
        """Test filtering with simple field selection."""
        # Mock GraphQL info with simple field selection
        mock_info = MagicMock()
        mock_field_node = MagicMock()

        mock_selection1 = create_field_node_mock("id")
        mock_selection2 = create_field_node_mock("name")

        mock_field_node.selection_set.selections = [mock_selection1, mock_selection2]
        mock_info.field_nodes = [mock_field_node]

        # Test data with more fields than requested
        result_data = {
            "id": "123",
            "name": "John Doe",
            "email": "john@example.com",  # Not requested
            "age": 30,  # Not requested
        }

        filtered = filter_mutation_result(result_data, mock_info)

        # Should only include requested fields
        assert "id" in filtered
        assert "name" in filtered
        assert "email" not in filtered
        assert "age" not in filtered
        assert filtered["id"] == "123"
        assert filtered["name"] == "John Doe"

    def test_filter_mutation_result_nested_fields(self) -> None:
        """Test filtering with nested field selection."""
        # Mock GraphQL info with nested selection
        mock_info = MagicMock()
        mock_field_node = MagicMock()

        # Simple field
        mock_id_selection = create_field_node_mock("id")

        # Nested field with sub-selections
        mock_user_name = create_field_node_mock("name")
        mock_user_email = create_field_node_mock("email")
        mock_user_selection = create_field_node_mock(
            """user""", selections=[mock_user_name, mock_user_email]
        )

        mock_field_node.selection_set.selections = [mock_id_selection, mock_user_selection]
        mock_info.field_nodes = [mock_field_node]

        # Test data with nested structure
        result_data = {
            "id": "post-123",
            "title": "My Post",  # Not requested
            "user": {
                "name": "John Doe",
                "email": "john@example.com",
                "age": 30,  # Not requested
                "profile": {"bio": "Developer"},  # Not requested
            },
            "comments": ["comment1", "comment2"],  # Not requested
        }

        filtered = filter_mutation_result(result_data, mock_info)

        # Should include id and filtered user object
        assert "id" in filtered
        assert "user" in filtered
        assert "title" not in filtered
        assert "comments" not in filtered

        # User object should be filtered
        user = filtered["user"]
        assert "name" in user
        assert "email" in user
        assert "age" not in user
        assert "profile" not in user

    def test_filter_mutation_result_missing_fields(self) -> None:
        """Test filtering when requested fields are missing from data."""
        mock_info = MagicMock()
        mock_field_node = MagicMock()

        mock_selection1 = create_field_node_mock("id")
        mock_selection2 = create_field_node_mock("missing_field")  # Not in data

        mock_field_node.selection_set.selections = [mock_selection1, mock_selection2]
        mock_info.field_nodes = [mock_field_node]

        result_data = {"id": "123", "name": "John"}

        filtered = filter_mutation_result(result_data, mock_info)

        # Should include existing field, skip missing field
        assert "id" in filtered
        assert "missing_field" not in filtered
        assert "name" not in filtered  # Not requested

    def test_filter_mutation_result_empty_selection(self) -> None:
        """Test filtering with empty selection set."""
        mock_info = MagicMock()
        mock_field_node = MagicMock()
        mock_field_node.selection_set.selections = []
        mock_info.field_nodes = [mock_field_node]

        result_data = {"id": "123", "name": "John"}

        filtered = filter_mutation_result(result_data, mock_info)

        # Should return empty dict
        assert filtered == {}

    def test_filter_mutation_result_no_field_nodes(self) -> None:
        """Test filtering when no field nodes are present."""
        mock_info = MagicMock()
        mock_info.field_nodes = []

        result_data = {"id": "123", "name": "John"}

        filtered = filter_mutation_result(result_data, mock_info)

        # Should return original data when no selection info
        assert filtered == result_data

    def test_filter_mutation_result_list_data(self) -> None:
        """Test filtering with list data in results."""
        mock_info = MagicMock()
        mock_field_node = MagicMock()

        mock_selection1 = create_field_node_mock("id")

        # Selection for list field
        mock_selection2 = create_field_node_mock("tags")

        mock_field_node.selection_set.selections = [mock_selection1, mock_selection2]
        mock_info.field_nodes = [mock_field_node]

        result_data = {
            "id": "123",
            "tags": ["python", "graphql", "testing"],
            "metadata": {"created": "2023-01-01"},  # Not requested
        }

        filtered = filter_mutation_result(result_data, mock_info)

        assert "id" in filtered
        assert "tags" in filtered
        assert "metadata" not in filtered
        assert filtered["tags"] == ["python", "graphql", "testing"]

    def test_filter_mutation_result_complex_nesting(self) -> None:
        """Test filtering with deeply nested structures."""
        mock_info = MagicMock()
        mock_field_node = MagicMock()

        # Create complex nested selection
        mock_author_name = create_field_node_mock("name")
        mock_author_selection = create_field_node_mock("author", selections=[mock_author_name])

        mock_title_selection = create_field_node_mock("title")

        mock_post_selection = create_field_node_mock(
            """post""", selections=[mock_author_selection, mock_title_selection]
        )
        mock_field_node.selection_set.selections = [mock_post_selection]
        mock_info.field_nodes = [mock_field_node]

        result_data = {
            "post": {
                "title": "GraphQL Best Practices",
                "content": "Long content here...",  # Not requested
                "author": {
                    "name": "Jane Smith",
                    "email": "jane@example.com",  # Not requested
                    "profile": {"bio": "Expert"},  # Not requested
                },
                "tags": ["graphql", "api"],  # Not requested
            },
            "metadata": {"timestamp": "2023-01-01"},  # Not requested
        }

        filtered = filter_mutation_result(result_data, mock_info)

        assert "post" in filtered
        assert "metadata" not in filtered

        post = filtered["post"]
        assert "title" in post
        assert "author" in post
        assert "content" not in post
        assert "tags" not in post

        author = post["author"]
        assert "name" in author
        assert "email" not in author
        assert "profile" not in author

    def test_filter_mutation_result_dataclass_compatibility(self) -> None:
        """Test that filtering works with dataclass-serialized data."""
        from dataclasses import asdict, dataclass

        @dataclass
        class User:
            id: str
            name: str
            email: str

        @dataclass
        class Post:
            id: str
            title: str
            author: User

        # Create test data
        user = User(id="user-1", name="John", email="john@example.com")
        post = Post(id="post-1", title="My Post", author=user)

        # Convert to dict (as would happen in mutation)
        result_dict = asdict(post)

        # Mock selection for just id and author.name
        mock_info = MagicMock()
        mock_field_node = MagicMock()

        mock_id_selection = create_field_node_mock("id")

        mock_author_name = create_field_node_mock("name")
        mock_author_selection = create_field_node_mock("author", selections=[mock_author_name])

        mock_field_node.selection_set.selections = [mock_id_selection, mock_author_selection]
        mock_info.field_nodes = [mock_field_node]

        filtered = filter_mutation_result(result_dict, mock_info)

        # Should be able to reconstruct filtered dataclass
        assert "id" in filtered
        assert "author" in filtered
        assert "title" not in filtered
        assert filtered["author"]["name"] == "John"
        assert "email" not in filtered["author"]
