"""Simple test script to verify HITL functionality."""

import tempfile
from pathlib import Path

from dutch_tax_agent.checkpoint_utils import generate_thread_id
from dutch_tax_agent.document_manager import DocumentManager
from dutch_tax_agent.session_manager import SessionManager


def test_document_manager():
    """Test document manager functionality."""
    print("Testing DocumentManager...")
    
    dm = DocumentManager()
    
    # Test document metadata creation
    metadata = dm.create_document_metadata("test.pdf", "abc123hash", 5)
    assert metadata["filename"] == "test.pdf"
    assert metadata["hash"] == "abc123hash"
    assert metadata["page_count"] == 5
    assert metadata["id"] == "abc123hash"[:12]
    
    # Test document removal
    docs = [
        {"id": "doc1", "filename": "file1.pdf", "hash": "hash1", "page_count": 1},
        {"id": "doc2", "filename": "file2.pdf", "hash": "hash2", "page_count": 2},
        {"id": "doc3", "filename": "file3.pdf", "hash": "hash3", "page_count": 3},
    ]
    
    updated_docs, removed_ids = dm.remove_documents(docs, doc_ids=["doc2"])
    assert len(updated_docs) == 2
    assert "doc2" in removed_ids
    assert updated_docs[0]["id"] == "doc1"
    assert updated_docs[1]["id"] == "doc3"
    
    # Test remove by filename
    updated_docs, removed_ids = dm.remove_documents(docs, filenames=["file1.pdf"])
    assert len(updated_docs) == 2
    assert "doc1" in removed_ids
    
    # Test remove all
    updated_docs, removed_ids = dm.remove_documents(docs, remove_all=True)
    assert len(updated_docs) == 0
    assert len(removed_ids) == 3
    
    print("✓ DocumentManager tests passed")


def test_session_manager():
    """Test session manager functionality."""
    print("\nTesting SessionManager...")
    
    # Use temporary registry
    with tempfile.TemporaryDirectory() as tmpdir:
        registry_path = Path(tmpdir) / "test_sessions.json"
        sm = SessionManager(registry_path=registry_path)
        
        # Create session
        thread_id = generate_thread_id("test")
        session = sm.create_session(thread_id, 2024, has_fiscal_partner=True)
        
        assert session["thread_id"] == thread_id, f"Expected {thread_id}, got {session['thread_id']}"
        assert session["tax_year"] == 2024, f"Expected 2024, got {session['tax_year']}"
        assert session["has_fiscal_partner"] is True, f"Expected True, got {session['has_fiscal_partner']}"
        assert session["status"] == "active", f"Expected 'active', got {session['status']}"
        
        # Get session
        retrieved = sm.get_session(thread_id)
        assert retrieved is not None, "Session should exist"
        assert retrieved["thread_id"] == thread_id, f"Expected {thread_id}, got {retrieved.get('thread_id')}"
        
        # List sessions (should have 1 active session)
        sessions = sm.list_sessions(active_only=True)
        assert len(sessions) == 1, f"Expected 1 active session, got {len(sessions)}"
        
        # Update session to completed
        sm.update_session(thread_id, {"status": "completed"})
        updated = sm.get_session(thread_id)
        assert updated["status"] == "completed", f"Expected 'completed', got {updated['status']}"
        
        # List active sessions (should be 0 now)
        sessions_active = sm.list_sessions(active_only=True)
        assert len(sessions_active) == 0, f"Expected 0 active sessions after completion, got {len(sessions_active)}"
        
        # List all sessions (should be 1)
        sessions_all = sm.list_sessions(active_only=False)
        assert len(sessions_all) == 1, f"Expected 1 total session, got {len(sessions_all)}"
        
        # Delete session
        sm.delete_session(thread_id)
        deleted = sm.get_session(thread_id)
        assert deleted is None, f"Session should be deleted, but got {deleted}"
    
    print("✓ SessionManager tests passed")


def test_thread_id_generation():
    """Test thread ID generation."""
    print("\nTesting thread ID generation...")
    
    thread_id = generate_thread_id("tax2024")
    assert thread_id.startswith("tax2024-")
    assert len(thread_id) > len("tax2024-")
    
    # Ensure uniqueness
    thread_id2 = generate_thread_id("tax2024")
    assert thread_id != thread_id2
    
    print("✓ Thread ID generation tests passed")


if __name__ == "__main__":
    print("Running HITL functionality tests...\n")
    
    try:
        test_thread_id_generation()
        test_document_manager()
        test_session_manager()
        
        print("\n" + "="*50)
        print("✓ All tests passed!")
        print("="*50)
        
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        exit(1)

