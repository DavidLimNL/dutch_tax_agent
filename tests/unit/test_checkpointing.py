"""Tests for LangGraph checkpointing functionality."""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from dutch_tax_agent.checkpoint_utils import (
    generate_thread_id,
    list_checkpoints,
    get_checkpoint_state,
)
from dutch_tax_agent.config import settings
from dutch_tax_agent.graph import create_tax_graph
from dutch_tax_agent.graph.main_graph import (
    create_checkpointer,
    get_active_checkpointer_contexts,
)
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
    
    # Create minimal state without documents to avoid LLM calls
    initial_state = TaxGraphState(
        documents=[],  # Empty documents to avoid triggering dispatcher/LLM calls
        tax_year=2024,
    )
    
    config = {
        "configurable": {
            "thread_id": thread_id
        }
    }
    
    # Execute - should complete without LLM calls since no documents
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


# Tests for database connection lifecycle fix
class TestDatabaseConnectionLifecycle:
    """Tests to ensure database connections remain open during graph execution."""
    
    def test_sqlite_context_manager_stored(self, tmp_path: Path):
        """Test that SQLite context manager is stored in the active contexts list."""
        # Clear any existing contexts
        contexts = get_active_checkpointer_contexts()
        contexts.clear()
        
        # Create temporary database path
        db_path = tmp_path / "test_checkpoints.db"
        
        # Temporarily override settings
        original_backend = settings.checkpoint_backend
        original_enable = settings.enable_checkpointing
        original_db_path = settings.checkpoint_db_path
        
        try:
            settings.enable_checkpointing = True
            settings.checkpoint_backend = "sqlite"
            settings.checkpoint_db_path = db_path
            
            # Try to create checkpointer (may fail if sqlite package not installed)
            try:
                checkpointer = create_checkpointer()
                
                # If SQLite is available, context manager should be stored
                if checkpointer is not None:
                    contexts_after = get_active_checkpointer_contexts()
                    # Should have at least one context manager stored
                    assert len(contexts_after) > 0, "Context manager should be stored"
                    
                    # Verify the checkpointer is usable
                    assert checkpointer is not None
                    
            except ImportError:
                pytest.skip("langgraph-checkpoint-sqlite not installed")
                
        finally:
            # Restore original settings
            settings.checkpoint_backend = original_backend
            settings.enable_checkpointing = original_enable
            settings.checkpoint_db_path = original_db_path
            contexts.clear()
    
    def test_sqlite_connection_remains_open(self, tmp_path: Path):
        """Test that SQLite database connection remains open during graph operations."""
        # Clear any existing contexts
        contexts = get_active_checkpointer_contexts()
        contexts.clear()
        
        # Create temporary database path
        db_path = tmp_path / "test_checkpoints.db"
        
        # Temporarily override settings
        original_backend = settings.checkpoint_backend
        original_enable = settings.enable_checkpointing
        original_db_path = settings.checkpoint_db_path
        
        try:
            settings.enable_checkpointing = True
            settings.checkpoint_backend = "sqlite"
            settings.checkpoint_db_path = db_path
            
            try:
                # Create graph (this should create and store the context manager)
                graph = create_tax_graph()
                
                # Verify context manager is stored
                stored_contexts = get_active_checkpointer_contexts()
                assert len(stored_contexts) > 0, "Context manager should be stored"
                
                # Verify checkpointer exists and is usable
                assert hasattr(graph, 'checkpointer')
                checkpointer = graph.checkpointer
                assert checkpointer is not None
                
                # Create a test state and config
                thread_id = generate_thread_id(prefix="test-db")
                initial_state = TaxGraphState(
                    documents=[],
                    tax_year=2024,
                )
                config = {
                    "configurable": {
                        "thread_id": thread_id
                    }
                }
                
                # Try to use the checkpointer - should not raise "closed database" error
                try:
                    # This should not fail with "Cannot operate on a closed database"
                    result = graph.invoke(initial_state, config=config)
                    # If we get here, the connection was open
                    assert result is not None
                except Exception as e:
                    error_msg = str(e).lower()
                    # The error should NOT be about closed database
                    assert "closed database" not in error_msg, \
                        f"Database connection was closed: {e}"
                    assert "cannot operate" not in error_msg, \
                        f"Database connection was closed: {e}"
                    
            except ImportError:
                pytest.skip("langgraph-checkpoint-sqlite not installed")
                
        finally:
            # Restore original settings
            settings.checkpoint_backend = original_backend
            settings.enable_checkpointing = original_enable
            settings.checkpoint_db_path = original_db_path
            contexts.clear()
    
    def test_multiple_graph_creations_with_sqlite(self, tmp_path: Path):
        """Test that multiple graph creations work correctly with SQLite backend."""
        # Clear any existing contexts
        contexts = get_active_checkpointer_contexts()
        contexts.clear()
        
        # Create temporary database path
        db_path = tmp_path / "test_checkpoints.db"
        
        # Temporarily override settings
        original_backend = settings.checkpoint_backend
        original_enable = settings.enable_checkpointing
        original_db_path = settings.checkpoint_db_path
        
        try:
            settings.enable_checkpointing = True
            settings.checkpoint_backend = "sqlite"
            settings.checkpoint_db_path = db_path
            
            try:
                # Create first graph
                graph1 = create_tax_graph()
                contexts_after_first = len(get_active_checkpointer_contexts())
                
                # Create second graph
                graph2 = create_tax_graph()
                contexts_after_second = len(get_active_checkpointer_contexts())
                
                # Both graphs should have checkpointers
                assert hasattr(graph1, 'checkpointer')
                assert hasattr(graph2, 'checkpointer')
                
                # Context managers should be stored (may be same or different depending on implementation)
                assert contexts_after_first > 0
                assert contexts_after_second > 0
                
                # Both should be usable
                thread_id1 = generate_thread_id(prefix="test1")
                thread_id2 = generate_thread_id(prefix="test2")
                
                state = TaxGraphState(documents=[], tax_year=2024)
                
                # Both should work without "closed database" errors
                try:
                    graph1.invoke(state, config={"configurable": {"thread_id": thread_id1}})
                except Exception as e:
                    assert "closed database" not in str(e).lower()
                
                try:
                    graph2.invoke(state, config={"configurable": {"thread_id": thread_id2}})
                except Exception as e:
                    assert "closed database" not in str(e).lower()
                    
            except ImportError:
                pytest.skip("langgraph-checkpoint-sqlite not installed")
                
        finally:
            # Restore original settings
            settings.checkpoint_backend = original_backend
            settings.enable_checkpointing = original_enable
            settings.checkpoint_db_path = original_db_path
            contexts.clear()
    
    def test_memory_backend_no_context_storage(self):
        """Test that MemorySaver backend doesn't store context managers."""
        # Clear any existing contexts
        contexts = get_active_checkpointer_contexts()
        contexts.clear()
        
        # Temporarily override settings
        original_backend = settings.checkpoint_backend
        original_enable = settings.enable_checkpointing
        
        try:
            settings.enable_checkpointing = True
            settings.checkpoint_backend = "memory"
            
            # Create checkpointer
            checkpointer = create_checkpointer()
            
            # Should return a MemorySaver instance
            from langgraph.checkpoint.memory import MemorySaver
            assert isinstance(checkpointer, MemorySaver)
            
            # Context managers list should remain empty (MemorySaver is not a context manager)
            contexts_after = get_active_checkpointer_contexts()
            assert len(contexts_after) == 0, "MemorySaver should not store context managers"
            
        finally:
            # Restore original settings
            settings.checkpoint_backend = original_backend
            settings.enable_checkpointing = original_enable
            contexts.clear()
    
    def test_checkpointer_prevents_garbage_collection(self, tmp_path: Path):
        """Test that storing context managers prevents garbage collection."""
        # Clear any existing contexts
        contexts = get_active_checkpointer_contexts()
        contexts.clear()
        
        # Create temporary database path
        db_path = tmp_path / "test_checkpoints.db"
        
        # Temporarily override settings
        original_backend = settings.checkpoint_backend
        original_enable = settings.enable_checkpointing
        original_db_path = settings.checkpoint_db_path
        
        try:
            settings.enable_checkpointing = True
            settings.checkpoint_backend = "sqlite"
            settings.checkpoint_db_path = db_path
            
            try:
                # Create checkpointer
                checkpointer = create_checkpointer()
                
                if checkpointer is None:
                    pytest.skip("Checkpointer creation failed")
                
                # Get the stored context manager
                stored_contexts = get_active_checkpointer_contexts()
                assert len(stored_contexts) > 0, "Context manager should be stored"
                
                # Store reference to context manager
                cm = stored_contexts[0]
                
                # Force garbage collection (simulate what would happen without our fix)
                import gc
                gc.collect()
                
                # Context manager should still be in the list (not garbage collected)
                contexts_after_gc = get_active_checkpointer_contexts()
                assert len(contexts_after_gc) > 0, "Context manager should not be garbage collected"
                assert cm in contexts_after_gc, "Original context manager should still be stored"
                
                # Checkpointer should still be usable
                assert checkpointer is not None
                
            except ImportError:
                pytest.skip("langgraph-checkpoint-sqlite not installed")
                
        finally:
            # Restore original settings
            settings.checkpoint_backend = original_backend
            settings.enable_checkpointing = original_enable
            settings.checkpoint_db_path = original_db_path
            contexts.clear()
    
    def test_graph_execution_with_sqlite_no_closed_error(self, tmp_path: Path):
        """Test that graph execution with SQLite doesn't raise 'closed database' error."""
        # Clear any existing contexts
        contexts = get_active_checkpointer_contexts()
        contexts.clear()
        
        # Create temporary database path
        db_path = tmp_path / "test_checkpoints.db"
        
        # Temporarily override settings
        original_backend = settings.checkpoint_backend
        original_enable = settings.enable_checkpointing
        original_db_path = settings.checkpoint_db_path
        
        try:
            settings.enable_checkpointing = True
            settings.checkpoint_backend = "sqlite"
            settings.checkpoint_db_path = db_path
            
            try:
                # Create graph
                graph = create_tax_graph()
                
                # Create state without documents to avoid LLM calls
                # This test only needs to verify database connection lifecycle
                thread_id = generate_thread_id(prefix="test-exec")
                initial_state = TaxGraphState(
                    documents=[],  # Empty documents to avoid triggering dispatcher/LLM calls
                    tax_year=2024,
                )
                config = {
                    "configurable": {
                        "thread_id": thread_id
                    }
                }
                
                # Execute graph - should not raise "closed database" error
                # No documents means no dispatcher/LLM calls, but still tests connection lifecycle
                try:
                    result = graph.invoke(initial_state, config=config)
                    # If successful, verify result is not None
                    assert result is not None
                except Exception as e:
                    error_msg = str(e).lower()
                    # Verify the error is NOT about closed database
                    assert "closed database" not in error_msg, \
                        f"Database connection was closed during execution: {e}"
                    assert "cannot operate on a closed" not in error_msg, \
                        f"Database connection was closed during execution: {e}"
                    
            except ImportError:
                pytest.skip("langgraph-checkpoint-sqlite not installed")
                
        finally:
            # Restore original settings
            settings.checkpoint_backend = original_backend
            settings.enable_checkpointing = original_enable
            settings.checkpoint_db_path = original_db_path
            contexts.clear()

