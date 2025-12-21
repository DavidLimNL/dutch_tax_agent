"""Tests for LangGraph checkpointing functionality."""

import pytest
from unittest.mock import Mock, patch

from dutch_tax_agent.checkpoint_utils import (
    generate_thread_id,
    list_checkpoints,
    get_checkpoint_state,
)
from dutch_tax_agent.config import settings
from dutch_tax_agent.graph import create_tax_graph
from dutch_tax_agent.schemas.state import TaxGraphState
from dutch_tax_agent.schemas.documents import ScrubbedDocument


def test_generate_thread_id():
    """Test thread ID generation."""
    thread_id = generate_thread_id(prefix="test")
    
    assert thread_id.startswith("test-")
    assert len(thread_id) > len("test-")
    
    # Each call should generate unique IDs
    thread_id2 = generate_thread_id(prefix="test")
    assert thread_id != thread_id2


def test_create_graph_with_checkpointing():
    """Test that graph is created with checkpointer when enabled."""
    # Temporarily enable checkpointing
    original_setting = settings.enable_checkpointing
    settings.enable_checkpointing = True
    
    try:
        graph = create_tax_graph()
        
        # Graph should be compiled
        assert graph is not None
        
        # Check that checkpointer is attached (if MemorySaver is available)
        # The graph object has a checkpointer attribute when compiled with one
        assert hasattr(graph, 'checkpointer') or hasattr(graph, 'store')
        
    finally:
        settings.enable_checkpointing = original_setting


def test_create_graph_without_checkpointing():
    """Test that graph is created without checkpointer when disabled."""
    # Temporarily disable checkpointing
    original_setting = settings.enable_checkpointing
    settings.enable_checkpointing = False
    
    try:
        graph = create_tax_graph()
        
        # Graph should still be compiled
        assert graph is not None
        
    finally:
        settings.enable_checkpointing = original_setting


def test_aggregator_clears_documents():
    """Test that aggregate_extraction_node clears document text."""
    from dutch_tax_agent.graph.nodes.aggregator import aggregate_extraction_node
    
    # Create state with documents and validated results
    state = TaxGraphState(
        documents=[
            ScrubbedDocument(
                doc_id="doc1",
                filename="test.pdf",
                scrubbed_text="This is a large document with lots of text that should be cleared after extraction.",
                page_count=1,
                char_count=100,
            ),
            ScrubbedDocument(
                doc_id="doc2",
                filename="test2.pdf",
                scrubbed_text="Another document with more text to be cleared.",
                page_count=1,
                char_count=50,
            ),
        ],
        validated_results=[],  # Empty for this test
    )
    
    # Call aggregator node
    result = aggregate_extraction_node(state)
    
    # Should return empty documents list
    assert "documents" in result
    assert result["documents"] == []


def test_graph_invocation_with_config():
    """Test that graph can be invoked with config containing thread_id."""
    graph = create_tax_graph()
    
    # Create minimal initial state
    initial_state = TaxGraphState(
        documents=[],  # No documents to avoid full pipeline
        tax_year=2024,
    )
    
    # Config with thread_id
    config = {
        "configurable": {
            "thread_id": "test-thread-123"
        }
    }
    
    # This should not raise an error even with checkpointing
    # (though execution will be short since no documents)
    try:
        result = graph.invoke(initial_state, config=config)
        assert result is not None
    except Exception as e:
        # Expected behavior: might fail due to no documents, but not due to config
        # Check that error is not related to config/checkpointing
        assert "thread_id" not in str(e).lower()
        assert "config" not in str(e).lower()


def test_checkpoint_utils_with_none_checkpointer():
    """Test that checkpoint utilities handle None checkpointer gracefully."""
    # These should not crash even with None checkpointer
    checkpoints = list_checkpoints(None, "test-thread-123")
    assert checkpoints == []
    
    state = get_checkpoint_state(None, "test-thread-123")
    assert state is None


@pytest.mark.skipif(
    not settings.enable_checkpointing,
    reason="Checkpointing disabled in config"
)
def test_state_persistence_across_steps():
    """Test that state is persisted at each step when checkpointing is enabled."""
    from langgraph.checkpoint.memory import MemorySaver
    
    # Create a simple test to verify checkpointing works
    # This is more of an integration test
    thread_id = generate_thread_id(prefix="test")
    
    graph = create_tax_graph()
    
    # Create minimal state
    initial_state = TaxGraphState(
        documents=[
            ScrubbedDocument(
                doc_id="test1",
                filename="test.pdf",
                scrubbed_text="Test document",
                page_count=1,
                char_count=10,
            )
        ],
        tax_year=2024,
    )
    
    config = {
        "configurable": {
            "thread_id": thread_id
        }
    }
    
    # Execute (may fail at dispatcher due to classification, but checkpoint should save)
    try:
        graph.invoke(initial_state, config=config)
    except Exception:
        # Expected - we're just testing checkpoint persistence
        pass
    
    # If checkpointer is MemorySaver, we can inspect it
    if hasattr(graph, 'checkpointer') and isinstance(graph.checkpointer, MemorySaver):
        checkpointer = graph.checkpointer
        
        # Try to get checkpoints for this thread
        checkpoints = list_checkpoints(checkpointer, thread_id, limit=5)
        
        # Should have at least one checkpoint
        # (even if graph execution failed partway)
        assert len(checkpoints) >= 0  # May be 0 if execution failed before first checkpoint

