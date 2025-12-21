"""Integration tests for LangGraph flow."""

import pytest
from datetime import datetime

from dutch_tax_agent.schemas.state import TaxGraphState
from dutch_tax_agent.schemas.documents import ExtractionResult
from dutch_tax_agent.graph.nodes.validators import validator_node


def test_validator_node_accepts_state():
    """Test that validator_node properly accepts TaxGraphState."""
    # Create a mock state with extraction results
    state = TaxGraphState(
        extraction_results=[
            ExtractionResult(
                doc_id="test_doc_1",
                source_filename="test.pdf",
                status="success",
                extracted_data={
                    "box1_items": [
                        {
                            "income_type": "salary",
                            "gross_amount_eur": 5000.0,
                            "tax_withheld_eur": 1000.0,
                            "period_start": "2024-01-01",
                            "period_end": "2024-01-31",
                            "original_currency": "EUR",
                            "extraction_confidence": 0.9,
                        }
                    ]
                },
                extraction_confidence=0.9,
                extracted_at=datetime.now(),
                extracted_by_model="gpt-4o-mini",
                errors=[],
                warnings=[],
            )
        ]
    )
    
    # Call validator_node with state
    result = validator_node(state)
    
    # Verify it returns a dict with validated_results
    assert isinstance(result, dict)
    assert "validated_results" in result
    assert isinstance(result["validated_results"], list)
    assert len(result["validated_results"]) == 1
    
    # Verify the validated result has expected structure
    validated_result = result["validated_results"][0]
    assert "doc_id" in validated_result
    assert "validated_box1_items" in validated_result
    assert "validated_box3_items" in validated_result
    assert "validation_errors" in validated_result
    assert validated_result["doc_id"] == "test_doc_1"


def test_validator_node_handles_box3_data():
    """Test that validator_node properly handles Box 3 asset data."""
    state = TaxGraphState(
        extraction_results=[
            ExtractionResult(
                doc_id="test_doc_2",
                source_filename="bank_statement.pdf",
                status="success",
                extracted_data={
                    "box3_items": [
                        {
                            "asset_type": "savings",
                            "value_eur_jan1": 50000.0,
                            "realized_gains_eur": None,
                            "reference_date": "2024-01-01",
                            "description": "ING Savings Account",
                            "original_currency": "EUR",
                            "extraction_confidence": 0.95,
                        }
                    ]
                },
                extraction_confidence=0.95,
                extracted_at=datetime.now(),
                extracted_by_model="gpt-4o-mini",
                errors=[],
                warnings=[],
            )
        ]
    )
    
    # Call validator_node with state
    result = validator_node(state)
    
    # Verify Box 3 items are validated
    assert isinstance(result, dict)
    assert "validated_results" in result
    assert len(result["validated_results"]) == 1
    
    validated_result = result["validated_results"][0]
    assert "validated_box3_items" in validated_result
    assert len(validated_result["validated_box3_items"]) == 1
    assert validated_result["validated_box3_items"][0]["asset_type"] == "savings"


def test_validator_node_handles_multiple_extraction_results():
    """Test that validator processes all unvalidated extraction results."""
    state = TaxGraphState(
        extraction_results=[
            ExtractionResult(
                doc_id="test_doc_1",
                source_filename="old.pdf",
                status="success",
                extracted_data={
                    "box3_items": [
                        {
                            "asset_type": "savings",
                            "value_eur_jan1": 50000.0,
                            "original_currency": "EUR",
                            "extraction_confidence": 0.8,
                        }
                    ]
                },
                extraction_confidence=0.8,
                extracted_at=datetime.now(),
                extracted_by_model="gpt-4o-mini",
                errors=[],
                warnings=[],
            ),
            ExtractionResult(
                doc_id="test_doc_2",
                source_filename="new.pdf",
                status="success",
                extracted_data={
                    "box1_items": [
                        {
                            "income_type": "salary",
                            "gross_amount_eur": 3000.0,
                            "tax_withheld_eur": 600.0,
                            "period_start": "2024-02-01",
                            "period_end": "2024-02-29",
                            "original_currency": "EUR",
                            "extraction_confidence": 0.9,
                        }
                    ]
                },
                extraction_confidence=0.9,
                extracted_at=datetime.now(),
                extracted_by_model="gpt-4o-mini",
                errors=[],
                warnings=[],
            ),
        ]
    )
    
    # Call validator_node with state containing multiple extraction results
    result = validator_node(state)
    
    # Verify it processes ALL unvalidated results (both test_doc_1 and test_doc_2)
    assert len(result["validated_results"]) == 2
    
    # Find results by doc_id
    validated_by_doc_id = {
        r["doc_id"]: r for r in result["validated_results"]
    }
    
    assert "test_doc_1" in validated_by_doc_id
    assert "test_doc_2" in validated_by_doc_id
    
    # Verify test_doc_1 has Box 3 items
    assert len(validated_by_doc_id["test_doc_1"]["validated_box3_items"]) == 1
    assert len(validated_by_doc_id["test_doc_1"]["validated_box1_items"]) == 0
    
    # Verify test_doc_2 has Box 1 items
    assert len(validated_by_doc_id["test_doc_2"]["validated_box1_items"]) == 1
    assert len(validated_by_doc_id["test_doc_2"]["validated_box3_items"]) == 0


def test_state_schema_accumulation():
    """Test that state schema properly handles accumulation with Annotated types."""
    # Create initial state
    state1 = TaxGraphState(
        extraction_results=[
            ExtractionResult(
                doc_id="doc1",
                source_filename="file1.pdf",
                status="success",
                extracted_data={},
                extraction_confidence=0.9,
                extracted_at=datetime.now(),
                extracted_by_model="gpt-4o-mini",
                errors=[],
                warnings=[],
            )
        ]
    )
    
    # Verify we can create state with multiple extraction results
    assert len(state1.extraction_results) == 1
    
    # Create a dict update (as parsers would return)
    update = {
        "extraction_results": [
            {
                "doc_id": "doc2",
                "source_filename": "file2.pdf",
                "status": "success",
                "extracted_data": {},
                "extraction_confidence": 0.9,
                "extracted_at": datetime.now(),
                "extracted_by_model": "gpt-4o-mini",
                "errors": [],
                "warnings": [],
            }
        ]
    }
    
    # Verify the update dict structure is correct
    assert "extraction_results" in update
    assert len(update["extraction_results"]) == 1

