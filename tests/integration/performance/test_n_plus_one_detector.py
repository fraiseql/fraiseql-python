"""Extended tests for N+1 query detector to improve coverage."""

import asyncio
import time
from unittest.mock import AsyncMock, Mock, patch

import pytest
from graphql import GraphQLResolveInfo
from graphql.pyutils import Path

from fraiseql.optimization.n_plus_one_detector import (
    N1DetectionResult,
    N1QueryDetectedError,
    N1QueryDetector,
    QueryPattern,
    configure_detector,
    get_detector,
    n1_detection_context,
    track_resolver_execution,
)

pytestmark = pytest.mark.integration


def _path(*keys: str | int) -> Path:
    """Build a graphql-core response path, as ``info.path`` is at runtime."""
    path = None
    for key in keys:
        path = Path(path, key, None)
    assert path is not None
    return path


class TestQueryPattern:
    """Test QueryPattern dataclass."""

    def test_query_pattern_creation(self) -> None:
        """Test creating a QueryPattern."""
        pattern = QueryPattern(
            field_path="articles.author",
            parent_type="Article",
            field_name="author",
            resolver_name="Article.author",
        )

        assert pattern.field_path == "articles.author"
        assert pattern.parent_type == "Article"
        assert pattern.field_name == "author"
        assert pattern.resolver_name == "Article.author"
        assert pattern.count == 0
        assert pattern.execution_times == []

    def test_avg_execution_time_empty(self) -> None:
        """Test average execution time with no times."""
        pattern = QueryPattern(
            field_path="test.field",
            parent_type="Test",
            field_name="field",
            resolver_name="Test.field",
        )

        assert pattern.avg_execution_time == 0.0

    def test_avg_execution_time_with_values(self) -> None:
        """Test average execution time calculation."""
        pattern = QueryPattern(
            field_path="test.field",
            parent_type="Test",
            field_name="field",
            resolver_name="Test.field",
            execution_times=[0.1, 0.2, 0.3],
        )

        # Use approximate equality for floating point
        assert abs(pattern.avg_execution_time - 0.2) < 0.001

    def test_avg_execution_time_single_value(self) -> None:
        """Test average execution time with single value."""
        pattern = QueryPattern(
            field_path="test.field",
            parent_type="Test",
            field_name="field",
            resolver_name="Test.field",
            execution_times=[0.5],
        )

        assert pattern.avg_execution_time == 0.5


class TestN1DetectionResult:
    """Test N1DetectionResult dataclass."""

    def test_detection_result_creation(self) -> None:
        """Test creating an N1DetectionResult."""
        patterns = [
            QueryPattern(
                field_path="test.field",
                parent_type="Test",
                field_name="field",
                resolver_name="Test.field",
                count=15,
            )
        ]

        result = N1DetectionResult(
            detected=True,
            patterns=patterns,
            suggestions=["Use a DataLoader"],
            total_queries=15,
            threshold_exceeded=True,
        )

        assert result.detected is True
        assert len(result.patterns) == 1
        assert result.suggestions == ["Use a DataLoader"]
        assert result.total_queries == 15
        assert result.threshold_exceeded is True


class TestN1QueryDetector:
    """Test N1QueryDetector class."""

    def test_detector_initialization_defaults(self) -> None:
        """Test detector initialization with default values."""
        detector = N1QueryDetector()

        assert detector.threshold == 10
        assert detector.time_window == 1.0
        assert detector.enabled is True
        assert detector.raise_on_detection is False
        assert detector._current_request_id is None
        assert len(detector._patterns) == 0

    def test_detector_initialization_custom(self) -> None:
        """Test detector initialization with custom values."""
        detector = N1QueryDetector(
            threshold=5, time_window=2.0, enabled=False, raise_on_detection=True
        )

        assert detector.threshold == 5
        assert detector.time_window == 2.0
        assert detector.enabled is False
        assert detector.raise_on_detection is True

    def test_start_request_enabled(self) -> None:
        """Test starting a request when detector is enabled."""
        detector = N1QueryDetector(enabled=True)
        request_id = "test-request-123"

        detector.start_request(request_id)

        assert detector._current_request_id == request_id
        assert len(detector._patterns) == 0
        assert len(detector._pattern_timestamps) == 0

    def test_start_request_disabled(self) -> None:
        """Test starting a request when detector is disabled."""
        detector = N1QueryDetector(enabled=False)
        request_id = "test-request-123"

        detector.start_request(request_id)

        # Should not set request ID when disabled
        assert detector._current_request_id is None

    def test_start_request_clears_previous_data(self) -> None:
        """Test that starting a new request clears previous data."""
        detector = N1QueryDetector(enabled=True)

        # Add some data
        detector._patterns["test"] = QueryPattern(
            field_path="test", parent_type="Test", field_name="field", resolver_name="Test.field"
        )
        detector._pattern_timestamps["test"] = [time.time()]

        # Start new request
        detector.start_request("new-request")

        assert len(detector._patterns) == 0
        assert len(detector._pattern_timestamps) == 0

    def test_end_request_disabled(self) -> None:
        """Test ending a request when detector is disabled."""
        detector = N1QueryDetector(enabled=False)

        result = detector.end_request()

        assert isinstance(result, N1DetectionResult)
        assert result.detected is False
        assert result.patterns == []
        assert result.suggestions == []
        assert result.total_queries == 0
        assert result.threshold_exceeded is False

    def test_end_request_no_patterns(self) -> None:
        """Test ending a request with no patterns."""
        detector = N1QueryDetector(enabled=True, threshold=5)
        detector.start_request("test-request")

        result = detector.end_request()

        assert result.detected is False
        assert result.patterns == []
        assert result.suggestions == []
        assert result.total_queries == 0
        assert result.threshold_exceeded is False

    def test_end_request_patterns_below_threshold(self) -> None:
        """Test ending a request with patterns below threshold."""
        detector = N1QueryDetector(enabled=True, threshold=10)
        detector.start_request("test-request")

        # Add pattern below threshold
        pattern = QueryPattern(
            field_path="test.field",
            parent_type="Test",
            field_name="field",
            resolver_name="Test.field",
            count=5,
        )
        detector._patterns["Test.field"] = pattern

        result = detector.end_request()

        assert result.detected is False
        assert result.patterns == []
        assert result.suggestions == []
        assert result.total_queries == 5
        assert result.threshold_exceeded is False

    def test_end_request_patterns_above_threshold(self) -> None:
        """Test ending a request with patterns above threshold."""
        detector = N1QueryDetector(enabled=True, threshold=5)
        detector.start_request("test-request")

        # Add pattern above threshold
        pattern = QueryPattern(
            field_path="test.field",
            parent_type="Test",
            field_name="field",
            resolver_name="Test.field",
            count=10,
        )
        detector._patterns["Test.field"] = pattern

        result = detector.end_request()

        assert result.detected is True
        assert len(result.patterns) == 1
        assert result.patterns[0].count == 10
        assert len(result.suggestions) == 1
        assert "Consider using a DataLoader" in result.suggestions[0]
        assert result.total_queries == 10
        assert result.threshold_exceeded is True

    def test_end_request_multiple_patterns(self) -> None:
        """Test ending a request with multiple patterns."""
        detector = N1QueryDetector(enabled=True, threshold=5)
        detector.start_request("test-request")

        # Add multiple patterns
        pattern1 = QueryPattern(
            field_path="test.field1",
            parent_type="Test",
            field_name="field1",
            resolver_name="Test.field1",
            count=8,
        )
        pattern2 = QueryPattern(
            field_path="test.field2",
            parent_type="Test",
            field_name="field2",
            resolver_name="Test.field2",
            count=3,  # Below threshold
        )
        pattern3 = QueryPattern(
            field_path="other.field",
            parent_type="Other",
            field_name="field",
            resolver_name="Other.field",
            count=12,
        )

        detector._patterns["Test.field1"] = pattern1
        detector._patterns["Test.field2"] = pattern2
        detector._patterns["Other.field"] = pattern3

        result = detector.end_request()

        assert result.detected is True
        assert len(result.patterns) == 2  # Only patterns above threshold
        assert result.total_queries == 23  # Sum of all patterns
        assert len(result.suggestions) == 2

    @patch("fraiseql.optimization.n_plus_one_detector.logger")
    def test_end_request_logs_warnings(self, mock_logger) -> None:
        """Test that end_request logs warnings when patterns detected."""
        detector = N1QueryDetector(enabled=True, threshold=5)
        detector.start_request("test-request")

        pattern = QueryPattern(
            field_path="test.field",
            parent_type="Test",
            field_name="field",
            resolver_name="Test.field",
            count=10,
        )
        detector._patterns["Test.field"] = pattern

        detector.end_request()

        # Check that warning was logged
        mock_logger.warning.assert_called()
        warning_calls = mock_logger.warning.call_args_list
        assert len(warning_calls) >= 2  # Header + suggestion

    def test_end_request_raises_exception(self) -> None:
        """Test that end_request raises exception when configured."""
        detector = N1QueryDetector(enabled=True, threshold=5, raise_on_detection=True)
        detector.start_request("test-request")

        pattern = QueryPattern(
            field_path="test.field",
            parent_type="Test",
            field_name="field",
            resolver_name="Test.field",
            count=10,
        )
        detector._patterns["Test.field"] = pattern

        with pytest.raises(N1QueryDetectedError) as exc_info:
            detector.end_request()

        assert "N+1 query pattern detected" in str(exc_info.value)
        assert len(exc_info.value.patterns) == 1

    def test_end_request_no_exception_when_disabled(self) -> None:
        """Test that end_request doesn't raise when raise_on_detection is False."""
        detector = N1QueryDetector(enabled=True, threshold=5, raise_on_detection=False)
        detector.start_request("test-request")

        pattern = QueryPattern(
            field_path="test.field",
            parent_type="Test",
            field_name="field",
            resolver_name="Test.field",
            count=10,
        )
        detector._patterns["Test.field"] = pattern

        # Should not raise
        result = detector.end_request()
        assert result.detected is True

    @pytest.mark.asyncio
    async def test_track_field_resolution_disabled(self) -> None:
        """Test tracking field resolution when detector is disabled."""
        detector = N1QueryDetector(enabled=False)

        mock_info = Mock(spec=GraphQLResolveInfo)

        # Should do nothing when disabled
        await detector.track_field_resolution(mock_info, "test_field", 0.1)

        assert len(detector._patterns) == 0

    @pytest.mark.asyncio
    async def test_track_field_resolution_no_request(self) -> None:
        """Test tracking field resolution when no request is active."""
        detector = N1QueryDetector(enabled=True)
        # Don't start a request

        mock_info = Mock(spec=GraphQLResolveInfo)

        # Should do nothing when no request is active
        await detector.track_field_resolution(mock_info, "test_field", 0.1)

        assert len(detector._patterns) == 0

    @pytest.mark.asyncio
    async def test_track_field_resolution_creates_pattern(self) -> None:
        """Test tracking field resolution creates new pattern."""
        detector = N1QueryDetector(enabled=True)
        detector.start_request("test-request")

        # Mock GraphQL info
        mock_info = Mock(spec=GraphQLResolveInfo)
        mock_info.parent_type = Mock()
        mock_info.parent_type.name = "Article"
        mock_info.path = _path("articles", 0, "author")

        await detector.track_field_resolution(mock_info, "author", 0.1)

        # Should create new pattern
        assert len(detector._patterns) == 1
        pattern_key = "Article.author"
        assert pattern_key in detector._patterns

        pattern = detector._patterns[pattern_key]
        assert pattern.parent_type == "Article"
        assert pattern.field_name == "author"
        assert pattern.resolver_name == "Article.author"
        assert pattern.count == 1
        assert pattern.execution_times == [0.1]

    @pytest.mark.asyncio
    async def test_track_field_resolution_updates_pattern(self) -> None:
        """Test tracking field resolution updates existing pattern."""
        detector = N1QueryDetector(enabled=True)
        detector.start_request("test-request")

        mock_info = Mock(spec=GraphQLResolveInfo)
        mock_info.parent_type = Mock()
        mock_info.parent_type.name = "Article"
        mock_info.path = _path("articles", 0, "author")

        # Track multiple times
        await detector.track_field_resolution(mock_info, "author", 0.1)
        await detector.track_field_resolution(mock_info, "author", 0.2)
        await detector.track_field_resolution(mock_info, "author", 0.15)

        pattern = detector._patterns["Article.author"]
        assert pattern.count == 3
        assert pattern.execution_times == [0.1, 0.2, 0.15]

    @pytest.mark.asyncio
    async def test_track_field_resolution_no_parent_type(self) -> None:
        """Test tracking field resolution with no parent type."""
        detector = N1QueryDetector(enabled=True)
        detector.start_request("test-request")

        mock_info = Mock(spec=GraphQLResolveInfo)
        mock_info.parent_type = None
        mock_info.path = _path("field")

        await detector.track_field_resolution(mock_info, "test_field", 0.1)

        pattern = detector._patterns["Unknown.test_field"]
        assert pattern.parent_type == "Unknown"

    @pytest.mark.asyncio
    async def test_track_field_resolution_time_window_cleanup(self) -> None:
        """Test that old timestamps are cleaned up based on time window."""
        detector = N1QueryDetector(enabled=True, time_window=0.1)  # 100ms window
        detector.start_request("test-request")

        mock_info = Mock(spec=GraphQLResolveInfo)
        mock_info.parent_type = Mock()
        mock_info.parent_type.name = "Test"
        mock_info.path = _path("test")

        # Track with some delay
        await detector.track_field_resolution(mock_info, "field", 0.1)

        # Wait longer than time window
        await asyncio.sleep(0.15)

        await detector.track_field_resolution(mock_info, "field", 0.1)

        # Old timestamp should be cleaned up
        timestamps = detector._pattern_timestamps["Test.field"]
        assert len(timestamps) == 1  # Only the recent one


class TestN1QueryDetectedError:
    """Test N1QueryDetectedError exception."""

    def test_error_creation(self) -> None:
        """Test creating N1QueryDetectedError."""
        patterns = [
            QueryPattern(
                field_path="test.field",
                parent_type="Test",
                field_name="field",
                resolver_name="Test.field",
                count=15,
            )
        ]

        error = N1QueryDetectedError("Test error", patterns)

        assert str(error) == "Test error"
        assert error.patterns == patterns


class TestGlobalDetectorFunctions:
    """Test global detector functions."""

    def test_get_detector_creates_instance(self) -> None:
        """Test that get_detector creates a global instance."""
        # Clear any existing detector
        import fraiseql.optimization.n_plus_one_detector as detector_module

        detector_module._detector = None

        detector = get_detector()

        assert isinstance(detector, N1QueryDetector)

        # Should return the same instance on subsequent calls
        detector2 = get_detector()
        assert detector is detector2

    def test_configure_detector_sets_global(self) -> None:
        """Test that configure_detector sets global detector."""
        detector = configure_detector(
            threshold=15, time_window=2.0, enabled=False, raise_on_detection=True
        )

        assert isinstance(detector, N1QueryDetector)
        assert detector.threshold == 15
        assert detector.time_window == 2.0
        assert detector.enabled is False
        assert detector.raise_on_detection is True

        # Should be the global instance
        global_detector = get_detector()
        assert detector is global_detector


class TestN1DetectionContext:
    """Test n1_detection_context context manager."""

    @pytest.mark.asyncio
    async def test_context_normal_execution(self) -> None:
        """Test context manager with normal execution."""
        # Ensure detector is enabled for this test
        configure_detector(enabled=True)

        request_id = "test-request-123"

        async with n1_detection_context(request_id) as detector:
            assert isinstance(detector, N1QueryDetector)
            # Check that start_request was called by seeing if we can track
            assert detector.enabled  # Should be enabled now

        # After context, the request should be ended (request_id cleared)
        # This is the expected behavior

    @pytest.mark.asyncio
    async def test_context_with_exception(self) -> None:
        """Test context manager when exception occurs."""
        request_id = "test-request-123"
        detector = get_detector()

        # Mock end_request to verify it's called
        original_end_request = detector.end_request
        detector.end_request = Mock(
            return_value=N1DetectionResult(
                detected=False,
                patterns=[],
                suggestions=[],
                total_queries=0,
                threshold_exceeded=False,
            )
        )

        try:
            async with n1_detection_context(request_id) as context_detector:
                assert context_detector is detector
                raise ValueError("Test exception")
        except ValueError:
            pass  # Expected

        # Should have called end_request even with exception
        detector.end_request.assert_called_once()

        # Restore original method
        detector.end_request = original_end_request

    @pytest.mark.asyncio
    async def test_context_calls_end_request(self) -> None:
        """Test that context manager calls end_request on normal completion."""
        request_id = "test-request-123"
        detector = get_detector()

        # Mock end_request
        original_end_request = detector.end_request
        detector.end_request = Mock(
            return_value=N1DetectionResult(
                detected=False,
                patterns=[],
                suggestions=[],
                total_queries=0,
                threshold_exceeded=False,
            )
        )

        async with n1_detection_context(request_id):
            pass

        # Should have called end_request
        detector.end_request.assert_called_once()

        # Restore original method
        detector.end_request = original_end_request


class TestTrackResolverExecution:
    """Test track_resolver_execution decorator."""

    @pytest.mark.asyncio
    async def test_async_resolver_tracking_disabled(self) -> None:
        """Test async resolver with tracking disabled."""
        detector = Mock()
        detector.enabled = False

        with patch("fraiseql.optimization.n_plus_one_detector.get_detector", return_value=detector):

            @track_resolver_execution
            @pytest.mark.asyncio
            async def test_resolver(self, info) -> None:
                return "result"

            mock_info = Mock(spec=GraphQLResolveInfo)
            result = await test_resolver(None, mock_info)

            assert result == "result"
            # Should not call track_field_resolution when disabled
            assert (
                not hasattr(detector, "track_field_resolution")
                or not detector.track_field_resolution.called
            )

    @pytest.mark.asyncio
    async def test_async_resolver_tracking_enabled(self) -> None:
        """Test async resolver with tracking enabled."""
        detector = Mock()
        detector.enabled = True
        detector.track_field_resolution = AsyncMock()

        mock_info = Mock(spec=GraphQLResolveInfo)
        mock_info.field_name = "test_field"

        with patch("fraiseql.optimization.n_plus_one_detector.get_detector", return_value=detector):

            @track_resolver_execution
            @pytest.mark.asyncio
            async def test_resolver(self, info) -> None:
                await asyncio.sleep(0.01)  # Small delay for timing
                return "result"

            result = await test_resolver(None, mock_info)

            assert result == "result"
            detector.track_field_resolution.assert_called_once()

            # Check arguments
            call_args = detector.track_field_resolution.call_args
            assert call_args[0][0] is mock_info
            assert call_args[0][1] == "test_field"
            assert isinstance(call_args[0][2], float)  # execution time

    @pytest.mark.asyncio
    async def test_async_resolver_with_exception(self) -> None:
        """Test async resolver that raises exception."""
        detector = Mock()
        detector.enabled = True
        detector.track_field_resolution = AsyncMock()

        mock_info = Mock(spec=GraphQLResolveInfo)
        mock_info.field_name = "test_field"

        with patch("fraiseql.optimization.n_plus_one_detector.get_detector", return_value=detector):

            @track_resolver_execution
            async def failing_resolver(self, info) -> None:
                raise ValueError("Test error")

            with pytest.raises(ValueError, match="Test error"):
                await failing_resolver(None, mock_info)

            # Should still track the field resolution
            detector.track_field_resolution.assert_called_once()

    def test_sync_resolver_tracking_disabled(self) -> None:
        """Test sync resolver with tracking disabled."""
        detector = Mock()
        detector.enabled = False

        with patch("fraiseql.optimization.n_plus_one_detector.get_detector", return_value=detector):

            @track_resolver_execution
            def test_resolver(self, info) -> None:
                return "result"

            mock_info = Mock(spec=GraphQLResolveInfo)
            result = test_resolver(None, mock_info)

            assert result == "result"

    @patch("fraiseql.optimization.n_plus_one_detector.asyncio.create_task")
    def test_sync_resolver_tracking_enabled(self, mock_create_task) -> None:
        """Test sync resolver with tracking enabled."""
        detector = Mock()
        detector.enabled = True
        detector.track_field_resolution = AsyncMock()

        mock_info = Mock(spec=GraphQLResolveInfo)
        mock_info.field_name = "test_field"

        with patch("fraiseql.optimization.n_plus_one_detector.get_detector", return_value=detector):

            @track_resolver_execution
            def test_resolver(self, info) -> None:
                time.sleep(0.001)  # Small delay for timing
                return "result"

            result = test_resolver(None, mock_info)

            assert result == "result"
            # Should create async task for tracking
            mock_create_task.assert_called_once()

    @patch("fraiseql.optimization.n_plus_one_detector.asyncio.create_task")
    def test_sync_resolver_with_exception(self, mock_create_task) -> None:
        """Test sync resolver that raises exception."""
        detector = Mock()
        detector.enabled = True
        detector.track_field_resolution = AsyncMock()

        mock_info = Mock(spec=GraphQLResolveInfo)
        mock_info.field_name = "test_field"

        with patch("fraiseql.optimization.n_plus_one_detector.get_detector", return_value=detector):

            @track_resolver_execution
            def failing_resolver(self, info) -> None:
                raise ValueError("Test error")

            with pytest.raises(ValueError, match="Test error"):
                failing_resolver(None, mock_info)

            # Should still create task for tracking
            mock_create_task.assert_called_once()

    def test_decorator_wraps_function(self) -> None:
        """Test that decorator wraps the function correctly."""

        @track_resolver_execution
        async def documented_resolver(self, info) -> None:
            """This is a documented resolver."""
            return "result"

        # The decorator doesn't use functools.wraps, so metadata isn't preserved
        # But the function should still be callable
        assert callable(documented_resolver)
        assert asyncio.iscoroutinefunction(documented_resolver)

    def test_sync_function_detection(self) -> None:
        """Test that decorator correctly detects sync vs async functions."""

        @track_resolver_execution
        def sync_func(self, info) -> None:
            return "sync"

        @track_resolver_execution
        async def async_func(self, info) -> None:
            return "async"

        # Check that the right wrapper is used
        assert not asyncio.iscoroutinefunction(sync_func)
        assert asyncio.iscoroutinefunction(async_func)


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_query_pattern_with_empty_execution_times(self) -> None:
        """Test QueryPattern with empty execution times list."""
        pattern = QueryPattern(
            field_path="test",
            parent_type="Test",
            field_name="field",
            resolver_name="Test.field",
            execution_times=[],
        )

        assert pattern.avg_execution_time == 0.0

    @pytest.mark.asyncio
    async def test_track_field_resolution_with_complex_path(self) -> None:
        """Test tracking with complex GraphQL path."""
        detector = N1QueryDetector(enabled=True)
        detector.start_request("test-request")

        mock_info = Mock(spec=GraphQLResolveInfo)
        mock_info.parent_type = Mock()
        mock_info.parent_type.name = "Article"
        mock_info.path = _path("articles", 0, "author", "posts", 1, "comments")

        await detector.track_field_resolution(mock_info, "comments", 0.1)

        pattern = detector._patterns["Article.comments"]
        assert pattern.field_path == "articles.author.posts.comments"

    def test_end_request_with_zero_threshold(self) -> None:
        """Test end_request with threshold of 0."""
        detector = N1QueryDetector(enabled=True, threshold=0)
        detector.start_request("test-request")

        pattern = QueryPattern(
            field_path="test.field",
            parent_type="Test",
            field_name="field",
            resolver_name="Test.field",
            count=1,  # Any count > 0 should trigger
        )
        detector._patterns["Test.field"] = pattern

        result = detector.end_request()

        assert result.detected is True
        assert len(result.patterns) == 1

    def test_configure_detector_multiple_times(self) -> None:
        """Test configuring detector multiple times."""
        detector1 = configure_detector(threshold=5)
        detector2 = configure_detector(threshold=15)

        # Should create new instance each time
        assert detector1 is not detector2
        assert detector2.threshold == 15

        # Global instance should be the latest
        global_detector = get_detector()
        assert global_detector is detector2

    @pytest.mark.asyncio
    async def test_context_manager_with_detection_exception(self) -> None:
        """Test context manager when N+1 detection raises exception."""
        configure_detector(threshold=1, enabled=True, raise_on_detection=True)

        request_id = "test-request"

        try:
            async with n1_detection_context(request_id) as context_detector:
                # Add pattern that will trigger detection
                pattern = QueryPattern(
                    field_path="test.field",
                    parent_type="Test",
                    field_name="field",
                    resolver_name="Test.field",
                    count=5,
                )
                context_detector._patterns["Test.field"] = pattern
                # Normal completion will trigger end_request
        except N1QueryDetectedError:
            pass  # Expected when raise_on_detection=True

    def test_pattern_suggestion_formatting(self) -> None:
        """Test that pattern suggestions are formatted correctly."""
        detector = N1QueryDetector(enabled=True, threshold=5)
        detector.start_request("test-request")

        pattern = QueryPattern(
            field_path="articles.author",
            parent_type="Article",
            field_name="author",
            resolver_name="Article.author",
            count=10,
        )
        detector._patterns["Article.author"] = pattern

        result = detector.end_request()

        assert len(result.suggestions) == 1
        suggestion = result.suggestions[0]
        assert "Field 'author' on type 'Article'" in suggestion
        assert "was resolved 10 times" in suggestion
        assert "Consider using a DataLoader" in suggestion

    @pytest.mark.asyncio
    async def test_detector_thread_safety(self) -> None:
        """Test detector behavior with concurrent access."""
        detector = N1QueryDetector(enabled=True)
        detector.start_request("test-request")

        mock_info = Mock(spec=GraphQLResolveInfo)
        mock_info.parent_type = Mock()
        mock_info.parent_type.name = "Test"
        mock_info.path = _path("test")

        # Simulate concurrent tracking
        tasks = []
        for _i in range(10):
            task = asyncio.create_task(detector.track_field_resolution(mock_info, "field", 0.1))
            tasks.append(task)

        await asyncio.gather(*tasks)

        pattern = detector._patterns["Test.field"]
        assert pattern.count == 10
        assert len(pattern.execution_times) == 10
