"""Simple test script to verify HITL functionality."""

import tempfile
from pathlib import Path

from dutch_tax_agent.checkpoint_utils import generate_thread_id
from dutch_tax_agent.document_manager import DocumentManager


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
        
        print("\n" + "="*50)
        print("✓ All tests passed!")
        print("="*50)
        
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        exit(1)

