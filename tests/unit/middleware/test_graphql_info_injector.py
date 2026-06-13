"""Unit tests for GraphQL info auto-injection middleware."""

from unittest.mock import MagicMock

import pytest

from fraiseql.middleware.graphql_info_injector import GraphQLInfoInjector


class TestGraphQLInfoInjection:
    """Tests for GraphQL info auto-injection."""

    def setup_method(self):
        """Set up test fixtures."""
        self.injector = GraphQLInfoInjector()

    def _create_mock_info(self):
        """Create mock GraphQLResolveInfo for testing."""
        return MagicMock(context={})

    @pytest.mark.asyncio
    async def test_info_injected_into_context(self):
        """Verify info is injected into context correctly."""
        mock_info = self._create_mock_info()

        @GraphQLInfoInjector.auto_inject
        async def resolver(info):
            return info.context.get("graphql_info")

        result = await resolver(mock_info)
        assert result == mock_info
        assert mock_info.context["graphql_info"] == mock_info

    @pytest.mark.asyncio
    async def test_explicit_info_parameter(self):
        """Verify explicit info parameter is injected properly."""
        mock_info = self._create_mock_info()

        @GraphQLInfoInjector.auto_inject
        async def resolver(info):
            return info

        result = await resolver(mock_info)
        assert result == mock_info
        assert mock_info.context["graphql_info"] == mock_info

    @pytest.mark.asyncio
    async def test_no_info_parameter_resolver(self):
        """Verify resolver without info parameter works."""
        @GraphQLInfoInjector.auto_inject
        async def resolver(param1, param2):
            return param1 + param2

        result = await resolver(1, 2)
        assert result == 3

    @pytest.mark.asyncio
    async def test_info_with_kwargs(self):
        """Verify info injection works with kwargs."""
        mock_info = self._create_mock_info()

        @GraphQLInfoInjector.auto_inject
        async def resolver(info, limit=100):
            return (info, limit)

        result = await resolver(info=mock_info, limit=50)
        assert result[0] == mock_info
        assert result[1] == 50
        assert mock_info.context["graphql_info"] == mock_info

    @pytest.mark.asyncio
    async def test_info_not_dict_context(self):
        """Verify handling when context is not a dict."""
        mock_info = MagicMock(context="not_a_dict")

        @GraphQLInfoInjector.auto_inject
        async def resolver(info):
            return info

        result = await resolver(mock_info)
        assert result == mock_info
        # Should not inject since context is not a dict

    @pytest.mark.asyncio
    async def test_backwards_compatibility(self):
        """Verify backwards compatibility with explicit info=info."""
        mock_info = self._create_mock_info()

        @GraphQLInfoInjector.auto_inject
        async def resolver(info=None):
            return info

        result = await resolver(mock_info)
        assert result == mock_info

    @pytest.mark.asyncio
    async def test_info_as_positional_arg(self):
        """Verify info injection works when passed as positional argument."""
        mock_info = self._create_mock_info()

        @GraphQLInfoInjector.auto_inject
        async def resolver(info, limit=100):
            return (info, limit)

        result = await resolver(mock_info, 50)
        assert result[0] == mock_info
        assert result[1] == 50
        assert mock_info.context["graphql_info"] == mock_info

    @pytest.mark.asyncio
    async def test_info_without_context_attribute(self):
        """Verify handling when info object has no context attribute."""
        mock_info = MagicMock(spec=[])  # No context attribute

        @GraphQLInfoInjector.auto_inject
        async def resolver(info):
            return info

        result = await resolver(mock_info)
        assert result == mock_info
        # Should not raise error, just skip injection

    @pytest.mark.asyncio
    async def test_info_with_none_context(self):
        """Verify handling when info.context is None."""
        mock_info = MagicMock(context=None)

        @GraphQLInfoInjector.auto_inject
        async def resolver(info):
            return info

        result = await resolver(mock_info)
        assert result == mock_info
        # Should not inject since context is None

    @pytest.mark.asyncio
    async def test_multiple_positional_args_with_info(self):
        """Verify info injection with multiple positional arguments."""
        mock_info = self._create_mock_info()

        @GraphQLInfoInjector.auto_inject
        async def resolver(obj, info, limit=10):
            return (obj, info, limit)

        result = await resolver("root", mock_info, 20)
        assert result[0] == "root"
        assert result[1] == mock_info
        assert result[2] == 20
        assert mock_info.context["graphql_info"] == mock_info

    @pytest.mark.asyncio
    async def test_info_not_in_args_when_expected(self):
        """Verify handling when info param exists but not passed."""
        @GraphQLInfoInjector.auto_inject
        async def resolver(info=None):
            return info

        # Call without passing info
        result = await resolver()
        assert result is None


class TestGraphQLInfoInjectionSync:
    """Tests for GraphQL info auto-injection on synchronous resolvers."""

    def setup_method(self):
        """Set up test fixtures."""
        self.injector = GraphQLInfoInjector()

    def _create_mock_info(self):
        """Create mock GraphQLResolveInfo for testing."""
        return MagicMock(context={})

    def test_sync_info_injected_into_context(self):
        """Verify info is injected into context correctly for sync resolvers."""
        mock_info = self._create_mock_info()

        @GraphQLInfoInjector.auto_inject
        def resolver(info):
            return info.context.get("graphql_info")

        result = resolver(mock_info)
        assert result == mock_info
        assert mock_info.context["graphql_info"] == mock_info

    def test_sync_explicit_info_parameter(self):
        """Verify explicit info parameter is injected properly in sync resolvers."""
        mock_info = self._create_mock_info()

        @GraphQLInfoInjector.auto_inject
        def resolver(info):
            return info

        result = resolver(mock_info)
        assert result == mock_info
        assert mock_info.context["graphql_info"] == mock_info

    def test_sync_no_info_parameter_resolver(self):
        """Verify sync resolver without info parameter works."""
        @GraphQLInfoInjector.auto_inject
        def resolver(param1, param2):
            return param1 + param2

        result = resolver(1, 2)
        assert result == 3

    def test_sync_info_with_kwargs(self):
        """Verify info injection works with kwargs in sync resolvers."""
        mock_info = self._create_mock_info()

        @GraphQLInfoInjector.auto_inject
        def resolver(info, limit=100):
            return (info, limit)

        result = resolver(info=mock_info, limit=50)
        assert result[0] == mock_info
        assert result[1] == 50
        assert mock_info.context["graphql_info"] == mock_info

    def test_sync_info_not_dict_context(self):
        """Verify handling when context is not a dict in sync resolvers."""
        mock_info = MagicMock(context="not_a_dict")

        @GraphQLInfoInjector.auto_inject
        def resolver(info):
            return info

        result = resolver(mock_info)
        assert result == mock_info
        # Should not inject since context is not a dict

    def test_sync_info_as_positional_arg(self):
        """Verify info injection works when passed as positional argument in sync resolvers."""
        mock_info = self._create_mock_info()

        @GraphQLInfoInjector.auto_inject
        def resolver(info, limit=100):
            return (info, limit)

        result = resolver(mock_info, 50)
        assert result[0] == mock_info
        assert result[1] == 50
        assert mock_info.context["graphql_info"] == mock_info

    def test_sync_info_without_context_attribute(self):
        """Verify handling when info object has no context attribute in sync resolvers."""
        mock_info = MagicMock(spec=[])  # No context attribute

        @GraphQLInfoInjector.auto_inject
        def resolver(info):
            return info

        result = resolver(mock_info)
        assert result == mock_info
        # Should not raise error, just skip injection

    def test_sync_info_with_none_context(self):
        """Verify handling when info.context is None in sync resolvers."""
        mock_info = MagicMock(context=None)

        @GraphQLInfoInjector.auto_inject
        def resolver(info):
            return info

        result = resolver(mock_info)
        assert result == mock_info
        # Should not inject since context is None

    def test_sync_multiple_positional_args_with_info(self):
        """Verify info injection with multiple positional arguments in sync resolvers."""
        mock_info = self._create_mock_info()

        @GraphQLInfoInjector.auto_inject
        def resolver(obj, info, limit=10):
            return (obj, info, limit)

        result = resolver("root", mock_info, 20)
        assert result[0] == "root"
        assert result[1] == mock_info
        assert result[2] == 20
        assert mock_info.context["graphql_info"] == mock_info

    def test_sync_backwards_compatibility(self):
        """Verify backwards compatibility with explicit info=info in sync resolvers."""
        mock_info = self._create_mock_info()

        @GraphQLInfoInjector.auto_inject
        def resolver(info=None):
            return info

        result = resolver(mock_info)
        assert result == mock_info

    def test_sync_info_not_in_args_when_expected(self):
        """Verify handling when info param exists but not passed in sync resolvers."""
        @GraphQLInfoInjector.auto_inject
        def resolver(info=None):
            return info

        # Call without passing info
        result = resolver()
        assert result is None
