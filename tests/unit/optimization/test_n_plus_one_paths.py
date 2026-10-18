"""Pattern paths recorded by the N+1 detector, from a real graphql-core ``Path``."""

from unittest.mock import Mock

import pytest
from graphql import GraphQLResolveInfo
from graphql.pyutils import Path

from fraiseql.optimization.n_plus_one_detector import N1QueryDetector


def _info(path: Path | None) -> Mock:
    info = Mock(spec=GraphQLResolveInfo)
    info.parent_type = Mock()
    info.parent_type.name = "Post"
    info.path = path
    return info


def _author_path(index: int) -> Path:
    return Path(Path(None, "posts", "Query"), index, None).add_key("author", "Post")


@pytest.fixture
def detector() -> N1QueryDetector:
    detector = N1QueryDetector(enabled=True)
    detector.start_request("req-1")
    return detector


class TestPatternPath:
    @pytest.mark.asyncio
    async def test_path_uses_response_keys_without_list_indices(
        self, detector: N1QueryDetector
    ) -> None:
        await detector.track_field_resolution(_info(_author_path(0)), "author", 0.01)

        assert detector._patterns["Post.author"].field_path == "posts.author"

    @pytest.mark.asyncio
    async def test_path_is_the_same_for_every_list_item(self, detector: N1QueryDetector) -> None:
        await detector.track_field_resolution(_info(_author_path(0)), "author", 0.01)
        await detector.track_field_resolution(_info(_author_path(1)), "author", 0.01)

        pattern = detector._patterns["Post.author"]
        assert pattern.field_path == "posts.author"
        assert pattern.count == 2

    @pytest.mark.asyncio
    async def test_missing_path_gives_empty_string(self, detector: N1QueryDetector) -> None:
        await detector.track_field_resolution(_info(None), "author", 0.01)

        assert detector._patterns["Post.author"].field_path == ""
