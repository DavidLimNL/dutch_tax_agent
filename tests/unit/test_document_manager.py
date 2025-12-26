"""Unit tests for DocumentManager: removal, deduplication, and recalculation."""

import pytest
from pathlib import Path
from datetime import date
from unittest.mock import Mock, patch

from dutch_tax_agent.document_manager import DocumentManager
from dutch_tax_agent.schemas.tax_entities import Box1Income, Box3Asset
from dutch_tax_agent.schemas.documents import ExtractionResult


class TestDocumentManager:
    """Tests for DocumentManager class."""
    
    @pytest.fixture
    def document_manager(self) -> DocumentManager:
        """Create a DocumentManager instance."""
        return DocumentManager()
    
    @pytest.fixture
    def sample_pdf(self, tmp_path: Path) -> Path:
        """Create a sample PDF file for testing."""
        pdf_path = tmp_path / "test_document.pdf"
        pdf_path.write_bytes(b"Sample PDF content for testing")
        return pdf_path
    
    @pytest.fixture
    def sample_processed_docs(self) -> list[dict]:
        """Sample processed documents metadata."""
        return [
            {
                "id": "abc123def456",
                "filename": "doc1.pdf",
                "hash": "abc123def4567890123456789012345678901234567890123456789012345678",
                "page_count": 2,
                "timestamp": "2024-01-01T00:00:00Z"
            },
            {
                "id": "xyz789ghi012",
                "filename": "doc2.pdf",
                "hash": "xyz789ghi0123456789012345678901234567890123456789012345678901234",
                "page_count": 3,
                "timestamp": "2024-01-02T00:00:00Z"
            }
        ]
    
    @pytest.fixture
    def sample_box1_items(self) -> list[Box1Income]:
        """Sample Box 1 income items."""
        return [
            Box1Income(
                source_doc_id="abc123def456",
                source_filename="doc1.pdf",
                income_type="salary",
                gross_amount_eur=5000.0,
                tax_withheld_eur=1500.0,
                period_start=date(2024, 1, 1),
                period_end=date(2024, 1, 31)
            ),
            Box1Income(
                source_doc_id="xyz789ghi012",
                source_filename="doc2.pdf",
                income_type="bonus",
                gross_amount_eur=2000.0,
                tax_withheld_eur=600.0,
                period_start=date(2024, 2, 1),
                period_end=date(2024, 2, 29)
            )
        ]
    
    @pytest.fixture
    def sample_box3_items(self) -> list[Box3Asset]:
        """Sample Box 3 asset items."""
        return [
            Box3Asset(
                source_doc_id="abc123def456",
                source_filename="doc1.pdf",
                asset_type="savings",
                value_eur_jan1=10000.0,
                value_eur_dec31=10500.0,
                account_number="NL91ABNA0417164300",
                description="Savings Account",
                reference_date=date(2024, 1, 1)
            ),
            Box3Asset(
                source_doc_id="abc123def456",
                source_filename="doc1.pdf",
                asset_type="checking",
                value_eur_jan1=5000.0,
                value_eur_dec31=4800.0,
                account_number="NL91ABNA0417164301",
                description="Checking Account",
                reference_date=date(2024, 1, 1)
            ),
            Box3Asset(
                source_doc_id="xyz789ghi012",
                source_filename="doc2.pdf",
                asset_type="savings",
                value_eur_jan1=15000.0,
                value_eur_dec31=16000.0,
                account_number="NL91ABNA0417164302",
                description="Investment Account",
                reference_date=date(2024, 1, 1)
            )
        ]
    
    def test_hash_pdf(self, document_manager: DocumentManager, sample_pdf: Path):
        """Test PDF hashing."""
        hash1 = document_manager.hash_pdf(sample_pdf)
        hash2 = document_manager.hash_pdf(sample_pdf)
        
        # Same file should produce same hash
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 produces 64 hex chars
        
        # Different content should produce different hash
        sample_pdf.write_bytes(b"Different content")
        hash3 = document_manager.hash_pdf(sample_pdf)
        assert hash3 != hash1
    
    def test_find_new_documents_by_hash(self, document_manager: DocumentManager, 
                                        sample_pdf: Path, sample_processed_docs: list[dict]):
        """Test finding new documents by hash."""
        # Create a PDF with known hash
        sample_pdf.write_bytes(b"test content")
        doc_hash = document_manager.hash_pdf(sample_pdf)
        doc_id = doc_hash[:12]
        
        # Add to processed docs
        processed_docs = sample_processed_docs + [{
            "id": doc_id,
            "filename": "test_document.pdf",
            "hash": doc_hash,
            "page_count": 1,
            "timestamp": "2024-01-01T00:00:00Z"
        }]
        
        # Should find no new documents
        new_docs = document_manager.find_new_documents([sample_pdf], processed_docs)
        assert len(new_docs) == 0
    
    def test_find_new_documents_by_id(self, document_manager: DocumentManager,
                                     sample_pdf: Path, sample_processed_docs: list[dict]):
        """Test finding new documents by ID (even if hash differs)."""
        # Create a PDF
        sample_pdf.write_bytes(b"test content")
        doc_hash = document_manager.hash_pdf(sample_pdf)
        doc_id = doc_hash[:12]
        
        # Add to processed docs with same ID but different hash (simulating edge case)
        processed_docs = sample_processed_docs + [{
            "id": doc_id,  # Same ID
            "filename": "test_document.pdf",
            "hash": "different_hash_that_would_not_match_but_id_would",
            "page_count": 1,
            "timestamp": "2024-01-01T00:00:00Z"
        }]
        
        # Should find no new documents (filtered by ID)
        new_docs = document_manager.find_new_documents([sample_pdf], processed_docs)
        assert len(new_docs) == 0
    
    def test_find_new_documents_actually_new(self, document_manager: DocumentManager,
                                           sample_pdf: Path, sample_processed_docs: list[dict]):
        """Test finding actually new documents."""
        # Create a new PDF with different content
        sample_pdf.write_bytes(b"completely new content that doesn't match")
        
        # Should find the new document
        new_docs = document_manager.find_new_documents([sample_pdf], sample_processed_docs)
        assert len(new_docs) == 1
        assert new_docs[0] == sample_pdf
    
    def test_remove_documents_by_id(self, document_manager: DocumentManager,
                                   sample_processed_docs: list[dict]):
        """Test removing documents by ID."""
        updated_docs, removed_ids = document_manager.remove_documents(
            sample_processed_docs,
            doc_ids=["abc123def456"]
        )
        
        assert len(updated_docs) == 1
        assert updated_docs[0]["id"] == "xyz789ghi012"
        assert len(removed_ids) == 1
        assert "abc123def456" in removed_ids
    
    def test_remove_documents_by_filename(self, document_manager: DocumentManager,
                                         sample_processed_docs: list[dict]):
        """Test removing documents by filename."""
        updated_docs, removed_ids = document_manager.remove_documents(
            sample_processed_docs,
            filenames=["doc1.pdf"]
        )
        
        assert len(updated_docs) == 1
        assert updated_docs[0]["filename"] == "doc2.pdf"
        assert len(removed_ids) == 1
        assert "abc123def456" in removed_ids
    
    def test_remove_documents_all(self, document_manager: DocumentManager,
                                  sample_processed_docs: list[dict]):
        """Test removing all documents."""
        updated_docs, removed_ids = document_manager.remove_documents(
            sample_processed_docs,
            remove_all=True
        )
        
        assert len(updated_docs) == 0
        assert len(removed_ids) == 2
    
    def test_recalculate_totals_removes_items(self, document_manager: DocumentManager,
                                             sample_box1_items: list[Box1Income],
                                             sample_box3_items: list[Box3Asset]):
        """Test that recalculation removes items from removed documents."""
        result = document_manager.recalculate_totals_from_items(
            sample_box1_items,
            sample_box3_items,
            removed_doc_ids=["abc123def456"]
        )
        
        # Box1 items from removed doc should be filtered out
        assert len(result["box1_income_items"]) == 1
        assert result["box1_income_items"][0].source_doc_id == "xyz789ghi012"
        
        # Box3 items from removed doc should be filtered out
        assert len(result["box3_asset_items"]) == 1
        assert result["box3_asset_items"][0].source_doc_id == "xyz789ghi012"
        
        # Totals should be recalculated
        assert result["box1_total_income"] == 2000.0
        assert result["box3_total_assets_jan1"] == 15000.0
    
    def test_recalculate_totals_keeps_all_items(self, document_manager: DocumentManager,
                                                sample_box1_items: list[Box1Income],
                                                sample_box3_items: list[Box3Asset]):
        """Test that recalculation keeps items when no documents are removed."""
        result = document_manager.recalculate_totals_from_items(
            sample_box1_items,
            sample_box3_items,
            removed_doc_ids=[]
        )
        
        # All items should remain
        assert len(result["box1_income_items"]) == 2
        assert len(result["box3_asset_items"]) == 3
        
        # Totals should be correct
        assert result["box1_total_income"] == 7000.0
        assert result["box3_total_assets_jan1"] == 30000.0
    
    def test_deduplicate_box3_assets_removes_duplicates(self, document_manager: DocumentManager):
        """Test that asset deduplication removes exact duplicates."""
        assets = [
            Box3Asset(
                source_doc_id="doc1",
                source_filename="doc1.pdf",
                asset_type="savings",
                value_eur_jan1=10000.0,
                value_eur_dec31=10500.0,
                account_number="NL91ABNA0417164300",
                description="Account 1",
                reference_date=date(2024, 1, 1)
            ),
            # Exact duplicate
            Box3Asset(
                source_doc_id="doc1",
                source_filename="doc1.pdf",
                asset_type="savings",
                value_eur_jan1=10000.0,
                value_eur_dec31=10500.0,
                account_number="NL91ABNA0417164300",
                description="Account 1",
                reference_date=date(2024, 1, 1)
            ),
            # Different account (should be kept)
            Box3Asset(
                source_doc_id="doc1",
                source_filename="doc1.pdf",
                asset_type="checking",
                value_eur_jan1=5000.0,
                value_eur_dec31=4800.0,
                account_number="NL91ABNA0417164301",
                description="Account 2",
                reference_date=date(2024, 1, 1)
            )
        ]
        
        deduplicated = document_manager._deduplicate_box3_assets(assets)
        
        # Should have 2 assets (duplicate removed)
        assert len(deduplicated) == 2
        assert deduplicated[0].account_number == "NL91ABNA0417164300"
        assert deduplicated[1].account_number == "NL91ABNA0417164301"
    
    def test_deduplicate_box3_assets_same_values_different_docs(self, document_manager: DocumentManager):
        """Test that assets with same values but different source_doc_id are kept."""
        assets = [
            Box3Asset(
                source_doc_id="doc1",
                source_filename="doc1.pdf",
                asset_type="savings",
                value_eur_jan1=10000.0,
                value_eur_dec31=10500.0,
                account_number="NL91ABNA0417164300",
                description="Account 1",
                reference_date=date(2024, 1, 1)
            ),
            # Same values but different source_doc_id (should be kept)
            Box3Asset(
                source_doc_id="doc2",
                source_filename="doc2.pdf",
                asset_type="savings",
                value_eur_jan1=10000.0,
                value_eur_dec31=10500.0,
                account_number="NL91ABNA0417164300",
                description="Account 1",
                reference_date=date(2024, 1, 1)
            )
        ]
        
        deduplicated = document_manager._deduplicate_box3_assets(assets)
        
        # Both should be kept (different source_doc_id)
        assert len(deduplicated) == 2
    
    def test_deduplicate_box3_assets_none_account_number(self, document_manager: DocumentManager):
        """Test deduplication with None account numbers."""
        assets = [
            Box3Asset(
                source_doc_id="doc1",
                source_filename="doc1.pdf",
                asset_type="savings",
                value_eur_jan1=10000.0,
                value_eur_dec31=10500.0,
                account_number=None,
                description="Account 1",
                reference_date=date(2024, 1, 1)
            ),
            # Duplicate with None account_number
            Box3Asset(
                source_doc_id="doc1",
                source_filename="doc1.pdf",
                asset_type="savings",
                value_eur_jan1=10000.0,
                value_eur_dec31=10500.0,
                account_number=None,
                description="Account 1",
                reference_date=date(2024, 1, 1)
            )
        ]
        
        deduplicated = document_manager._deduplicate_box3_assets(assets)
        
        # Duplicate should be removed
        assert len(deduplicated) == 1
    
    def test_deduplicate_box3_assets_value_tolerance(self, document_manager: DocumentManager):
        """Test that deduplication uses value tolerance (rounds to 2 decimals)."""
        assets = [
            Box3Asset(
                source_doc_id="doc1",
                source_filename="doc1.pdf",
                asset_type="savings",
                value_eur_jan1=10000.001,  # Rounds to 10000.00
                value_eur_dec31=10500.002,  # Rounds to 10500.00
                account_number="NL91ABNA0417164300",
                description="Account 1",
                reference_date=date(2024, 1, 1)
            ),
            # Should be considered duplicate (rounded to same value)
            Box3Asset(
                source_doc_id="doc1",
                source_filename="doc1.pdf",
                asset_type="savings",
                value_eur_jan1=10000.004,  # Also rounds to 10000.00
                value_eur_dec31=10500.003,  # Also rounds to 10500.00
                account_number="NL91ABNA0417164300",
                description="Account 1",
                reference_date=date(2024, 1, 1)
            )
        ]
        
        deduplicated = document_manager._deduplicate_box3_assets(assets)
        
        # Should be considered duplicates (rounded to same values)
        assert len(deduplicated) == 1
    
    def test_create_document_metadata(self, document_manager: DocumentManager):
        """Test creating document metadata."""
        metadata = document_manager.create_document_metadata(
            filename="test.pdf",
            doc_hash="abcdef1234567890123456789012345678901234567890123456789012345678",
            page_count=5
        )
        
        assert metadata["id"] == "abcdef123456"  # First 12 chars
        assert metadata["filename"] == "test.pdf"
        assert metadata["hash"] == "abcdef1234567890123456789012345678901234567890123456789012345678"
        assert metadata["page_count"] == 5
        assert "timestamp" in metadata
    
    def test_recalculate_from_extraction_results(self, document_manager: DocumentManager):
        """Test filtering extraction results after document removal."""
        extraction_results = [
            ExtractionResult(
                doc_id="doc1",
                source_filename="doc1.pdf",
                status="success",
                extracted_data={}
            ),
            ExtractionResult(
                doc_id="doc2",
                source_filename="doc2.pdf",
                status="success",
                extracted_data={}
            ),
            ExtractionResult(
                doc_id="doc3",
                source_filename="doc3.pdf",
                status="success",
                extracted_data={}
            )
        ]
        
        result = document_manager.recalculate_from_extraction_results(
            extraction_results,
            removed_doc_ids=["doc1", "doc3"]
        )
        
        assert len(result["extraction_results"]) == 1
        assert result["extraction_results"][0].doc_id == "doc2"


class TestDocumentRemovalIntegration:
    """Integration tests for document removal with recalculation."""
    
    @pytest.fixture
    def document_manager(self) -> DocumentManager:
        return DocumentManager()
    
    def test_remove_document_filters_all_related_data(self, document_manager: DocumentManager):
        """Test that removing a document filters all related Box1 and Box3 items."""
        # Create items from two documents
        box1_items = [
            Box1Income(
                source_doc_id="doc1",
                source_filename="doc1.pdf",
                income_type="salary",
                gross_amount_eur=5000.0,
                tax_withheld_eur=1500.0,
                period_start=date(2024, 1, 1),
                period_end=date(2024, 1, 31)
            ),
            Box1Income(
                source_doc_id="doc2",
                source_filename="doc2.pdf",
                income_type="bonus",
                gross_amount_eur=2000.0,
                tax_withheld_eur=600.0,
                period_start=date(2024, 2, 1),
                period_end=date(2024, 2, 29)
            )
        ]
        
        box3_items = [
            Box3Asset(
                source_doc_id="doc1",
                source_filename="doc1.pdf",
                asset_type="savings",
                value_eur_jan1=10000.0,
                value_eur_dec31=10500.0,
                account_number="ACC1",
                description="Account 1",
                reference_date=date(2024, 1, 1)
            ),
            Box3Asset(
                source_doc_id="doc2",
                source_filename="doc2.pdf",
                asset_type="checking",
                value_eur_jan1=5000.0,
                value_eur_dec31=4800.0,
                account_number="ACC2",
                description="Account 2",
                reference_date=date(2024, 1, 1)
            )
        ]
        
        # Remove doc1
        result = document_manager.recalculate_totals_from_items(
            box1_items,
            box3_items,
            removed_doc_ids=["doc1"]
        )
        
        # Verify only doc2 items remain
        assert len(result["box1_income_items"]) == 1
        assert result["box1_income_items"][0].source_doc_id == "doc2"
        assert result["box1_total_income"] == 2000.0
        
        assert len(result["box3_asset_items"]) == 1
        assert result["box3_asset_items"][0].source_doc_id == "doc2"
        assert result["box3_total_assets_jan1"] == 5000.0
    
    def test_remove_multiple_documents(self, document_manager: DocumentManager):
        """Test removing multiple documents at once."""
        box1_items = [
            Box1Income(
                source_doc_id="doc1",
                source_filename="doc1.pdf",
                income_type="salary",
                gross_amount_eur=5000.0,
                tax_withheld_eur=1500.0,
                period_start=date(2024, 1, 1),
                period_end=date(2024, 1, 31)
            ),
            Box1Income(
                source_doc_id="doc2",
                source_filename="doc2.pdf",
                income_type="bonus",
                gross_amount_eur=2000.0,
                tax_withheld_eur=600.0,
                period_start=date(2024, 2, 1),
                period_end=date(2024, 2, 29)
            ),
            Box1Income(
                source_doc_id="doc3",
                source_filename="doc3.pdf",
                income_type="salary",
                gross_amount_eur=3000.0,
                tax_withheld_eur=900.0,
                period_start=date(2024, 3, 1),
                period_end=date(2024, 3, 31)
            )
        ]
        
        box3_items = [
            Box3Asset(
                source_doc_id="doc1",
                source_filename="doc1.pdf",
                asset_type="savings",
                value_eur_jan1=10000.0,
                account_number="ACC1",
                description="Account 1",
                reference_date=date(2024, 1, 1)
            ),
            Box3Asset(
                source_doc_id="doc2",
                source_filename="doc2.pdf",
                asset_type="checking",
                value_eur_jan1=5000.0,
                account_number="ACC2",
                description="Account 2",
                reference_date=date(2024, 1, 1)
            ),
            Box3Asset(
                source_doc_id="doc3",
                source_filename="doc3.pdf",
                asset_type="savings",
                value_eur_jan1=8000.0,
                account_number="ACC3",
                description="Account 3",
                reference_date=date(2024, 1, 1)
            )
        ]
        
        # Remove doc1 and doc2
        result = document_manager.recalculate_totals_from_items(
            box1_items,
            box3_items,
            removed_doc_ids=["doc1", "doc2"]
        )
        
        # Only doc3 should remain
        assert len(result["box1_income_items"]) == 1
        assert result["box1_income_items"][0].source_doc_id == "doc3"
        assert result["box1_total_income"] == 3000.0
        
        assert len(result["box3_asset_items"]) == 1
        assert result["box3_asset_items"][0].source_doc_id == "doc3"
        assert result["box3_total_assets_jan1"] == 8000.0


class TestAgentDocumentRemoval:
    """Tests for DutchTaxAgent.remove_documents method."""
    
    @pytest.fixture
    def mock_graph(self) -> Mock:
        """Create a mock graph with checkpointer."""
        graph = Mock()
        graph.checkpointer = Mock()
        graph.update_state = Mock()
        return graph
    
    @pytest.fixture
    def session_manager(self, tmp_path: Path):
        """Create a SessionManager instance."""
        from dutch_tax_agent.session_manager import SessionManager
        return SessionManager(registry_path=tmp_path / "test_sessions.json")
    
    @pytest.fixture
    def sample_state(self):
        """Create a sample TaxGraphState for testing."""
        from dutch_tax_agent.schemas.state import TaxGraphState
        from dutch_tax_agent.schemas.documents import ExtractionResult
        from datetime import date
        
        return TaxGraphState(
            tax_year=2024,
            session_id="test-thread",
            status="awaiting_human",
            next_action="await_human",
            processed_documents=[
                {
                    "id": "doc1",
                    "filename": "doc1.pdf",
                    "hash": "hash1",
                    "page_count": 2,
                    "timestamp": "2024-01-01T00:00:00Z"
                },
                {
                    "id": "doc2",
                    "filename": "doc2.pdf",
                    "hash": "hash2",
                    "page_count": 3,
                    "timestamp": "2024-01-02T00:00:00Z"
                }
            ],
            extraction_results=[
                ExtractionResult(
                    doc_id="doc1",
                    source_filename="doc1.pdf",
                    status="success",
                    extracted_data={}
                ),
                ExtractionResult(
                    doc_id="doc2",
                    source_filename="doc2.pdf",
                    status="success",
                    extracted_data={}
                )
            ],
            validated_results=[
                {"doc_id": "doc1", "validated_box1_items": [], "validated_box3_items": []},
                {"doc_id": "doc2", "validated_box1_items": [], "validated_box3_items": []}
            ],
            box1_income_items=[
                Box1Income(
                    source_doc_id="doc1",
                    source_filename="doc1.pdf",
                    income_type="salary",
                    gross_amount_eur=5000.0,
                    tax_withheld_eur=1500.0,
                    period_start=date(2024, 1, 1),
                    period_end=date(2024, 1, 31)
                ),
                Box1Income(
                    source_doc_id="doc2",
                    source_filename="doc2.pdf",
                    income_type="bonus",
                    gross_amount_eur=2000.0,
                    tax_withheld_eur=600.0,
                    period_start=date(2024, 2, 1),
                    period_end=date(2024, 2, 29)
                )
            ],
            box3_asset_items=[
                Box3Asset(
                    source_doc_id="doc1",
                    source_filename="doc1.pdf",
                    asset_type="savings",
                    value_eur_jan1=10000.0,
                    value_eur_dec31=10500.0,
                    account_number="ACC1",
                    description="Account 1",
                    reference_date=date(2024, 1, 1)
                ),
                Box3Asset(
                    source_doc_id="doc2",
                    source_filename="doc2.pdf",
                    asset_type="checking",
                    value_eur_jan1=5000.0,
                    value_eur_dec31=4800.0,
                    account_number="ACC2",
                    description="Account 2",
                    reference_date=date(2024, 1, 1)
                )
            ],
            box1_total_income=7000.0,
            box3_total_assets_jan1=15000.0
        )
    
    def test_remove_documents_by_id_filters_all_data(
        self, mock_graph: Mock, session_manager, sample_state
    ):
        """Test that remove_documents filters all related data correctly."""
        from dutch_tax_agent.agent import DutchTaxAgent
        from dutch_tax_agent.schemas.state import TaxGraphState
        
        thread_id = "test-thread"
        session_manager.create_session(thread_id, tax_year=2024)
        
        # Mock get_current_state to return sample_state
        session_manager.get_current_state = Mock(return_value=sample_state)
        
        # Mock updated state after removal
        updated_state = TaxGraphState(**sample_state.model_dump())
        updated_state.processed_documents = [sample_state.processed_documents[1]]  # Keep only doc2
        updated_state.extraction_results = [sample_state.extraction_results[1]]
        updated_state.validated_results = [sample_state.validated_results[1]]
        updated_state.box1_income_items = [sample_state.box1_income_items[1]]
        updated_state.box3_asset_items = [sample_state.box3_asset_items[1]]
        updated_state.box1_total_income = 2000.0
        updated_state.box3_total_assets_jan1 = 5000.0
        
        # Return updated state on second call
        session_manager.get_current_state.side_effect = [sample_state, updated_state]
        
        with patch('dutch_tax_agent.agent.create_tax_graph', return_value=mock_graph):
            agent = DutchTaxAgent(thread_id=thread_id, tax_year=2024)
            agent.session_manager = session_manager
            
            result = agent.remove_documents(doc_ids=["doc1"])
            
            # Verify update_state was called
            mock_graph.update_state.assert_called_once()
            call_args = mock_graph.update_state.call_args
            config = call_args[0][0]
            updates = call_args[0][1]
            
            assert config["configurable"]["thread_id"] == thread_id
            assert len(updates["processed_documents"]) == 1
            assert updates["processed_documents"][0]["id"] == "doc2"
            assert len(updates["extraction_results"]) == 1
            assert updates["extraction_results"][0].doc_id == "doc2"
            assert len(updates["validated_results"]) == 1
            assert updates["validated_results"][0]["doc_id"] == "doc2"
            assert len(updates["box1_income_items"]) == 1
            assert updates["box1_income_items"][0].source_doc_id == "doc2"
            assert len(updates["box3_asset_items"]) == 1
            assert updates["box3_asset_items"][0].source_doc_id == "doc2"
            assert updates["box1_total_income"] == 2000.0
            assert updates["box3_total_assets_jan1"] == 5000.0
    
    def test_remove_documents_verifies_persistence(
        self, mock_graph: Mock, session_manager, sample_state
    ):
        """Test that remove_documents verifies state was persisted."""
        from dutch_tax_agent.agent import DutchTaxAgent
        from dutch_tax_agent.schemas.state import TaxGraphState
        
        thread_id = "test-thread"
        session_manager.create_session(thread_id, tax_year=2024)
        
        # Mock get_current_state - first call returns original, second returns updated
        updated_state = TaxGraphState(**sample_state.model_dump())
        updated_state.processed_documents = [sample_state.processed_documents[1]]
        updated_state.box1_total_income = 2000.0
        updated_state.box3_total_assets_jan1 = 5000.0
        
        session_manager.get_current_state = Mock(side_effect=[sample_state, updated_state])
        
        with patch('dutch_tax_agent.agent.create_tax_graph', return_value=mock_graph):
            agent = DutchTaxAgent(thread_id=thread_id, tax_year=2024)
            agent.session_manager = session_manager
            
            result = agent.remove_documents(doc_ids=["doc1"])
            
            # Should verify state was persisted
            assert session_manager.get_current_state.call_count == 2
            assert result.processed_documents[0]["id"] == "doc2"
    
    def test_remove_documents_raises_if_state_not_found(
        self, mock_graph: Mock, session_manager
    ):
        """Test that remove_documents raises if session not found."""
        from dutch_tax_agent.agent import DutchTaxAgent
        
        thread_id = "non-existent"
        session_manager.get_current_state = Mock(return_value=None)
        
        with patch('dutch_tax_agent.agent.create_tax_graph', return_value=mock_graph):
            agent = DutchTaxAgent(thread_id=thread_id, tax_year=2024)
            agent.session_manager = session_manager
            
            with pytest.raises(ValueError, match="Session.*not found"):
                agent.remove_documents(doc_ids=["doc1"])
    
    def test_remove_documents_by_filename(
        self, mock_graph: Mock, session_manager, sample_state
    ):
        """Test removing documents by filename."""
        from dutch_tax_agent.agent import DutchTaxAgent
        from dutch_tax_agent.schemas.state import TaxGraphState
        
        thread_id = "test-thread"
        session_manager.create_session(thread_id, tax_year=2024)
        
        updated_state = TaxGraphState(**sample_state.model_dump())
        updated_state.processed_documents = [sample_state.processed_documents[1]]
        updated_state.box1_total_income = 2000.0
        updated_state.box3_total_assets_jan1 = 5000.0
        
        session_manager.get_current_state = Mock(side_effect=[sample_state, updated_state])
        
        with patch('dutch_tax_agent.agent.create_tax_graph', return_value=mock_graph):
            agent = DutchTaxAgent(thread_id=thread_id, tax_year=2024)
            agent.session_manager = session_manager
            
            result = agent.remove_documents(filenames=["doc1.pdf"])
            
            # Verify doc1 was removed
            call_args = mock_graph.update_state.call_args
            updates = call_args[0][1]
            assert len(updates["processed_documents"]) == 1
            assert updates["processed_documents"][0]["filename"] == "doc2.pdf"
    
    def test_remove_documents_deduplicates_assets(
        self, mock_graph: Mock, session_manager
    ):
        """Test that remove_documents deduplicates Box 3 assets."""
        from dutch_tax_agent.agent import DutchTaxAgent
        from dutch_tax_agent.schemas.state import TaxGraphState
        from datetime import date
        
        thread_id = "test-thread"
        session_manager.create_session(thread_id, tax_year=2024)
        
        # Create state with duplicate assets
        state = TaxGraphState(
            tax_year=2024,
            session_id=thread_id,
            status="awaiting_human",
            next_action="await_human",
            processed_documents=[
                {
                    "id": "doc1",
                    "filename": "doc1.pdf",
                    "hash": "hash1",
                    "page_count": 2,
                    "timestamp": "2024-01-01T00:00:00Z"
                }
            ],
            box3_asset_items=[
                # Duplicate assets
                Box3Asset(
                    source_doc_id="doc1",
                    source_filename="doc1.pdf",
                    asset_type="savings",
                    value_eur_jan1=10000.0,
                    value_eur_dec31=10500.0,
                    account_number="ACC1",
                    description="Account 1",
                    reference_date=date(2024, 1, 1)
                ),
                Box3Asset(
                    source_doc_id="doc1",
                    source_filename="doc1.pdf",
                    asset_type="savings",
                    value_eur_jan1=10000.0,
                    value_eur_dec31=10500.0,
                    account_number="ACC1",
                    description="Account 1",
                    reference_date=date(2024, 1, 1)
                )
            ],
            box3_total_assets_jan1=20000.0  # Wrong total (duplicates)
        )
        
        updated_state = TaxGraphState(**state.model_dump())
        updated_state.box3_asset_items = [state.box3_asset_items[0]]  # Deduplicated
        updated_state.box3_total_assets_jan1 = 10000.0  # Correct total
        
        session_manager.get_current_state = Mock(side_effect=[state, updated_state])
        
        with patch('dutch_tax_agent.agent.create_tax_graph', return_value=mock_graph):
            agent = DutchTaxAgent(thread_id=thread_id, tax_year=2024)
            agent.session_manager = session_manager
            
            # Remove no documents, but should still deduplicate
            result = agent.remove_documents(doc_ids=[])
            
            # Verify deduplication happened
            call_args = mock_graph.update_state.call_args
            updates = call_args[0][1]
            # Should have only 1 asset after deduplication
            assert len(updates["box3_asset_items"]) == 1
            assert updates["box3_total_assets_jan1"] == 10000.0

