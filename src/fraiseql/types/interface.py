"""GraphQL interface type decorator for FraiseQL.

Interfaces are abstract types that define a set of fields that multiple
object types can implement. This is useful for polymorphic queries.
"""

from collections.abc import Callable
from typing import TypeVar, dataclass_transform, overload

from fraiseql.fields import fraise_field
from fraiseql.types.constructor import define_fraiseql_type
from fraiseql.utils.fields import patch_missing_field_types

T = TypeVar("T", bound=type)


@dataclass_transform(kw_only_default=True, field_specifiers=(fraise_field,))
@overload
def fraise_interface(_cls: None = None) -> Callable[[T], T]: ...
@overload
def fraise_interface(_cls: T) -> T: ...


def fraise_interface(_cls: T | None = None) -> T | Callable[[T], T]:
    """Decorator to mark a class as a GraphQL interface type.

    Interfaces define a contract that implementing types must follow. All fields
    defined in the interface must be present in implementing types with compatible
    types. This enables polymorphic queries and type-safe GraphQL operations.

    Args:
        _cls: The interface class to decorate (when used without parentheses)

    Returns:
        The decorated class registered as a GraphQL interface

    Examples:
        Basic Node interface for Global Object Identification::\

            @fraise_interface
            class Node:
                id: UUID

            @fraise_type(implements=[Node])
            class User:
                id: UUID
                name: str
                email: str

            @fraise_type(implements=[Node])
            class Post:
                id: UUID
                title: str
                content: str

            # GraphQL query can now use fragments:
            # query {
            #   node(id: "123") {
            #     id
            #     ... on User {
            #       name
            #       email
            #     }
            #     ... on Post {
            #       title
            #       content
            #     }
            #   }
            # }

        Interface with computed fields::\

            @fraise_interface
            class Timestamped:
                created_at: datetime
                updated_at: datetime

                @field(description="Time since creation")
                def age(self) -> timedelta:
                    return datetime.utcnow() - self.created_at

            @fraise_type(implements=[Timestamped])
            class Article:
                id: UUID
                title: str
                created_at: datetime
                updated_at: datetime

                # Must implement the computed field from interface
                @field(description="Time since creation")
                def age(self) -> timedelta:
                    return datetime.utcnow() - self.created_at

        Interface for content types with metadata::\

            @fraise_interface
            class Content:
                id: UUID
                title: str
                slug: str
                status: ContentStatus
                author_id: UUID

                @field(description="Content author")
                async def author(self, info) -> User:
                    db = info.context["db"]
                    return await db.find_one("user_view", {"id": self.author_id})

            @fraise_type(implements=[Content])
            class BlogPost:
                id: UUID
                title: str
                slug: str
                status: ContentStatus
                author_id: UUID
                content: str
                tags: list[str]

                @field(description="Content author")
                async def author(self, info) -> User:
                    # Implementation must match interface signature
                    db = info.context["db"]
                    return await db.find_one("user_view", {"id": self.author_id})

            @fraise_type(implements=[Content])
            class VideoPost:
                id: UUID
                title: str
                slug: str
                status: ContentStatus
                author_id: UUID
                video_url: str
                duration: int

                @field(description="Content author")
                async def author(self, info) -> User:
                    db = info.context["db"]
                    return await db.find_one("user_view", {"id": self.author_id})

        Multiple interface implementation::\

            @fraise_interface
            class Searchable:
                search_text: str

                @field(description="Search ranking score")
                def search_score(self, query: str) -> float:
                    # Simple text matching score
                    return query.lower() in self.search_text.lower()

            @fraise_interface
            class Taggable:
                tags: list[str]

                @field(description="Check if content has tag")
                def has_tag(self, tag: str) -> bool:
                    return tag in self.tags

            @fraise_type(implements=[Node, Searchable, Taggable])
            class Document:
                id: UUID
                title: str
                content: str
                tags: list[str]

                # Computed field for Searchable interface
                @field
                def search_text(self) -> str:
                    return f"{self.title} {self.content}"

                @field(description="Search ranking score")
                def search_score(self, query: str) -> float:
                    title_match = query.lower() in self.title.lower()
                    content_match = query.lower() in self.content.lower()
                    return (2.0 if title_match else 0.0) + (1.0 if content_match else 0.0)

                @field(description="Check if content has tag")
                def has_tag(self, tag: str) -> bool:
                    return tag in self.tags

        Interface for permission-based access::\

            @fraise_interface
            class Ownable:
                owner_id: UUID

                @field(description="Check if user owns this resource")
                def is_owned_by(self, user_id: UUID) -> bool:
                    return self.owner_id == user_id

                @field(description="Check if user can edit this resource")
                async def can_edit(self, info, user_id: UUID) -> bool:
                    # Default implementation - can be overridden
                    return self.owner_id == user_id

            @fraise_type(implements=[Ownable])
            class Project:
                id: UUID
                name: str
                owner_id: UUID
                collaborator_ids: list[UUID]

                @field(description="Check if user owns this resource")
                def is_owned_by(self, user_id: UUID) -> bool:
                    return self.owner_id == user_id

                @field(description="Check if user can edit this resource")
                async def can_edit(self, info, user_id: UUID) -> bool:
                    # Override: owners and collaborators can edit
                    return (self.owner_id == user_id or
                            user_id in self.collaborator_ids)

    Notes:
        - All interface fields must be implemented by concrete types
        - Field types in implementations must be compatible with interface types
        - Computed fields (@field methods) must have matching signatures
        - Interfaces enable polymorphic queries with GraphQL fragments
        - Multiple interface inheritance is supported
        - Use interfaces to share common fields and behavior across types
        - Resolver functions in interfaces provide default implementations
    """

    def wrap(cls: T) -> T:
        from fraiseql.gql.schema_builder import SchemaRegistry

        patch_missing_field_types(cls)
        # Use "interface" as the kind
        cls = define_fraiseql_type(cls, kind="interface")  # type: ignore[assignment,arg-type]
        SchemaRegistry.get_instance().register_interface(cls)
        return cls

    return wrap if _cls is None else wrap(_cls)
