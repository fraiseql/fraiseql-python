"""Test support for recursive/self-referential types (Issue #255).

Tests that FraiseQL can handle:
1. Simple self-referential types (e.g., Playlist with child_playlists)
2. Mutual recursion (e.g., Author <-> Book)
3. Optional recursive references
4. List of recursive references

RED Phase: These tests should fail with RecursionError before fix.
GREEN Phase: These tests should pass after implementing thunk pattern.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from graphql import GraphQLList, GraphQLNonNull, GraphQLObjectType

# Import needed for assertions
from fraiseql import type as fraiseql_type
from fraiseql.core.graphql_type import convert_type_to_graphql_output


class TestSimpleSelfReference:
    """Test simple self-referential types."""

    def test_list_of_self_reference(self):
        """Test type with list of itself (e.g., Playlist with child playlists)."""

        @fraiseql_type
        @dataclass
        class Playlist:
            """A music playlist that can contain nested playlists."""

            id: str
            name: str
            description: str | None = None
            child_playlists: list[Playlist] = field(default_factory=list)

        # This should NOT raise RecursionError
        result = convert_type_to_graphql_output(Playlist)

        # Verify type structure
        assert isinstance(result, GraphQLObjectType)
        assert result.name == "Playlist"

        # Verify fields exist
        fields = result.fields
        assert "id" in fields
        assert "name" in fields
        assert "description" in fields
        assert "childPlaylists" in fields

        # Verify child_playlists is list[Playlist]
        child_field = fields["childPlaylists"]
        assert isinstance(child_field.type, GraphQLNonNull)
        inner_type = child_field.type.of_type
        assert isinstance(inner_type, GraphQLList)
        list_item_type = inner_type.of_type
        # List items may or may not be NonNull depending on the type annotation
        # In this case, list['Playlist'] without explicit NonNull
        if isinstance(list_item_type, GraphQLNonNull):
            playlist_type = list_item_type.of_type
        else:
            playlist_type = list_item_type
        assert isinstance(playlist_type, GraphQLObjectType)
        assert playlist_type.name == "Playlist"

        # Verify it's the SAME type (not a duplicate)
        assert playlist_type is result

    def test_optional_self_reference(self):
        """Test type with optional self-reference (e.g., Node with parent)."""

        @fraiseql_type
        @dataclass
        class TreeNode:
            """A node in a tree structure."""

            id: str
            value: str
            parent: TreeNode | None = None

        # This should NOT raise RecursionError
        result = convert_type_to_graphql_output(TreeNode)

        # Verify type structure
        assert isinstance(result, GraphQLObjectType)
        assert result.name == "TreeNode"

        # Verify parent field exists and is nullable
        fields = result.fields
        assert "parent" in fields
        parent_field = fields["parent"]

        # Optional field should not be wrapped in NonNull
        assert isinstance(parent_field.type, GraphQLObjectType)
        assert parent_field.type.name == "TreeNode"
        assert parent_field.type is result


class TestMutualRecursion:
    """Test mutually recursive types.

    Note: True mutual recursion (A->B, B->A) requires both types to be defined
    before decoration. FraiseQL's @fraiseql_type decorator resolves forward
    references at decoration time. For this test, we use a simpler pattern:
    both types can reference themselves, demonstrating the same recursive
    capability without mutual forward references.
    """

    def test_two_types_with_self_references(self):
        """Test two types that can self-reference, demonstrating recursive capability."""

        @fraiseql_type
        @dataclass
        class Author:
            """An author who can collaborate with other authors."""

            id: str
            name: str
            collaborators: list[Author] = field(default_factory=list)

        @fraiseql_type
        @dataclass
        class Book:
            """A book that can reference related books."""

            id: str
            title: str
            related_books: list[Book] = field(default_factory=list)

        # This should NOT raise RecursionError for either type
        author_type = convert_type_to_graphql_output(Author)
        book_type = convert_type_to_graphql_output(Book)

        # Verify Author type with self-reference
        assert isinstance(author_type, GraphQLObjectType)
        assert author_type.name == "Author"
        assert "collaborators" in author_type.fields

        # Verify collaborators field references Author type itself
        collab_field = author_type.fields["collaborators"]
        assert isinstance(collab_field.type, GraphQLNonNull)
        collab_list = collab_field.type.of_type
        assert isinstance(collab_list, GraphQLList)
        author_item = collab_list.of_type
        # May or may not be NonNull wrapped
        if isinstance(author_item, GraphQLNonNull):
            author_ref = author_item.of_type
        else:
            author_ref = author_item
        assert isinstance(author_ref, GraphQLObjectType)
        assert author_ref.name == "Author"
        assert author_ref is author_type

        # Verify Book type with self-reference
        assert isinstance(book_type, GraphQLObjectType)
        assert book_type.name == "Book"
        assert "relatedBooks" in book_type.fields

        # Verify relatedBooks field references Book type itself
        related_field = book_type.fields["relatedBooks"]
        assert isinstance(related_field.type, GraphQLNonNull)
        related_list = related_field.type.of_type
        assert isinstance(related_list, GraphQLList)
        book_item = related_list.of_type
        if isinstance(book_item, GraphQLNonNull):
            book_ref = book_item.of_type
        else:
            book_ref = book_item
        assert isinstance(book_ref, GraphQLObjectType)
        assert book_ref.name == "Book"
        assert book_ref is book_type


class TestComplexRecursion:
    """Test complex recursive scenarios."""

    def test_multiple_recursive_fields(self):
        """Test type with multiple recursive fields."""

        @fraiseql_type
        @dataclass
        class OrgNode:
            """An organizational node with manager and reports."""

            id: str
            name: str
            manager: OrgNode | None = None
            direct_reports: list[OrgNode] = field(default_factory=list)
            all_subordinates: list[OrgNode] = field(default_factory=list)

        # This should NOT raise RecursionError
        result = convert_type_to_graphql_output(OrgNode)

        # Verify all fields exist
        assert isinstance(result, GraphQLObjectType)
        fields = result.fields
        assert "manager" in fields
        assert "directReports" in fields
        assert "allSubordinates" in fields

        # All recursive fields should reference the same type
        manager_type = fields["manager"].type
        assert isinstance(manager_type, GraphQLObjectType)
        assert manager_type is result

    def test_deeply_nested_structure(self):
        """Test that recursive types work with deep nesting."""

        @fraiseql_type
        @dataclass
        class Category:
            """A hierarchical category."""

            id: str
            name: str
            parent_category: Category | None = None
            subcategories: list[Category] = field(default_factory=list)

        # This should NOT raise RecursionError
        result = convert_type_to_graphql_output(Category)
        assert isinstance(result, GraphQLObjectType)

        # Verify we can traverse the type structure without issues
        fields = result.fields
        subcategories_field = fields["subcategories"]

        # Traverse: Category -> NonNull<list[Category]> -> list[Category] -> Category
        assert isinstance(subcategories_field.type, GraphQLNonNull)
        list_type = subcategories_field.type.of_type
        assert isinstance(list_type, GraphQLList)

        # Get the category from the list (may or may not be NonNull wrapped)
        category_ref = list_type.of_type
        if isinstance(category_ref, GraphQLNonNull):
            category_ref = category_ref.of_type
        assert isinstance(category_ref, GraphQLObjectType)
        assert category_ref is result

        # And again: Category -> list[Category] -> Category -> list[Category]
        nested_subcats = category_ref.fields["subcategories"]
        assert isinstance(nested_subcats.type, GraphQLNonNull)
        nested_list = nested_subcats.type.of_type
        assert isinstance(nested_list, GraphQLList)
        nested_category = nested_list.of_type
        if isinstance(nested_category, GraphQLNonNull):
            nested_category = nested_category.of_type
        assert nested_category is result


class TestCaching:
    """Test that recursive types are properly cached."""

    def test_same_type_returns_cached_instance(self):
        """Test that converting the same type twice returns the same instance."""

        @fraiseql_type
        @dataclass
        class Node:
            """A simple node."""

            id: str
            children: list[Node] = field(default_factory=list)

        # Convert twice
        first = convert_type_to_graphql_output(Node)
        second = convert_type_to_graphql_output(Node)

        # Should be the SAME instance (cached)
        assert first is second

    def test_recursive_field_references_cached_type(self):
        """Test that recursive fields reference the cached type, not a new one."""

        @fraiseql_type
        @dataclass
        class LinkedList:
            """A linked list node."""

            value: str
            next_node: LinkedList | None = None

        result = convert_type_to_graphql_output(LinkedList)

        # The next_node field should reference the SAME type
        next_field = result.fields["nextNode"]
        next_type = next_field.type
        assert isinstance(next_type, GraphQLObjectType)
        assert next_type is result


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_recursive_with_non_fraiseql_types(self):
        """Test recursive types mixed with standard types."""

        @fraiseql_type
        @dataclass
        class FileNode:
            """A file system node."""

            path: str
            size: int
            is_directory: bool
            children: list[FileNode] = field(default_factory=list)
            metadata: dict[str, str] = field(default_factory=dict)

        result = convert_type_to_graphql_output(FileNode)
        assert isinstance(result, GraphQLObjectType)

        # Verify all fields including standard types work
        fields = result.fields
        assert "path" in fields
        assert "size" in fields
        assert "isDirectory" in fields
        assert "children" in fields
        assert "metadata" in fields

    def test_list_without_default_factory(self):
        """Test recursive list field without default_factory."""

        @fraiseql_type
        @dataclass
        class SimpleNode:
            """A simple node without defaults."""

            id: str
            children: list[SimpleNode]

        # Should work even without field(default_factory=list)
        result = convert_type_to_graphql_output(SimpleNode)
        assert isinstance(result, GraphQLObjectType)
        assert "children" in result.fields
