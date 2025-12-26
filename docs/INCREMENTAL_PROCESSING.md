# Incremental Document Processing Flow

## Overview

When you add documents after the first ingestion, **ALL new documents go through the full pipeline**: parsing, PII scrubbing, extraction, validation, and aggregation. Here's the complete flow:

## Phase 1: Parsing & PII Scrubbing (ALWAYS Happens)

Location: `main.py::ingest_documents()` lines 145-203

**Every incremental ingestion:**

1. **Deduplication** (lines 133-141)
   ```python
   # Get existing state
   state = self.session_manager.get_current_state(self.graph.checkpointer, self.thread_id)
   
   # Filter for new documents only (SHA256 hash comparison)
   pdf_paths = self.document_manager.find_new_documents(
       pdf_paths, 
       state.processed_documents
   )
   ```

2. **PDF Parsing** (lines 157-181)
   ```python
   for pdf_path in pdf_paths:
       # Parse PDF
       result = self.pdf_parser.parse(pdf_path)
       
       # Generate hash
       doc_hash = self.document_manager.hash_pdf(pdf_path)
       
       # Create metadata
       metadata = self.document_manager.create_document_metadata(...)
       doc_metadata.append(metadata)
       
       parsed_docs.append({
           "text": result["text"],
           "filename": pdf_path.name,
           "page_count": result["page_count"],
       })
   ```

3. **PII Scrubbing** (lines 186-197)
   ```python
   # ZERO-TRUST: Documents that fail scrubbing are excluded
   scrubbed_docs = self.pii_scrubber.scrub_batch(parsed_docs)
   ```

**This happens BEFORE the graph is invoked**, so there's no way for unscrubbed documents to reach the LLM.

## Phase 2: Graph Loop (Extraction & Aggregation)

Location: `main.py::ingest_documents()` lines 270-293

### State Update

```python
updates = {
    "documents": scrubbed_docs,  # NEW scrubbed documents only
    "processed_documents": state.processed_documents + doc_metadata,  # Append metadata
    "next_action": "ingest_more",  # Signal to loop back
}

final_state = self.session_manager.update_and_resume(
    self.graph,
    self.thread_id,
    updates
)
```

### Graph Execution Flow

1. **Graph Resumes** from checkpoint (last node was `hitl_control`)

2. **HITL Control Node** sees `next_action="ingest_more"`
   - Location: `graph/nodes/hitl_control.py` lines 35-53
   - Routes to `dispatcher` with `Command(goto="dispatcher")`

3. **Dispatcher** processes new documents
   - Classifies documents
   - Creates `Send` objects for parallel routing

4. **Parser Agents** (parallel execution)
   - Extract structured data from each new document
   - Results accumulated in `extraction_results` (uses `Annotated[list, add]`)

5. **Validators** (parallel execution)
   - Validate extracted data
   - Normalize currencies
   - Results accumulated in `validated_results` (uses `Annotated[list, add]`)

6. **Aggregator** combines ALL data
   - Location: `graph/nodes/aggregator.py`
   - **FIXED**: Now uses `Annotated[list, add]` for `box1_income_items` and `box3_asset_items`
   - New items are **appended** to existing items
   - Lines 543-544:
     ```python
     "validation_errors": list(state.validation_errors) + all_errors,
     "validation_warnings": list(state.validation_warnings) + all_warnings,
     ```

7. **Reducer** recalculates totals
   - Sums ALL `box1_income_items` (old + new)
   - Sums ALL `box3_asset_items` (old + new)

8. **HITL Control** pauses again
   - Sets `next_action="await_human"`
   - Waits for next command

## State Accumulation Strategy

### Using `Annotated[list, add]`

The state schema uses LangGraph's `add` reducer for accumulation:

```python
# In state.py
extraction_results: Annotated[list[ExtractionResult], add] = Field(...)
validated_results: Annotated[list[dict], add] = Field(...)
box1_income_items: Annotated[list[Box1Income], add] = Field(...)  # FIXED
box3_asset_items: Annotated[list[Box3Asset], add] = Field(...)    # FIXED
```

**How `add` works:**
- When a node returns `{"box1_income_items": [new_items]}`, LangGraph **appends** `new_items` to the existing list
- This ensures incremental additions accumulate rather than replace

### Document Metadata Tracking

```python
# Simple list concatenation (not using add reducer)
"processed_documents": state.processed_documents + doc_metadata
```

This tracks which documents have been processed for deduplication.

## Example: Two Ingestion Runs

### Run 1: Initial
```bash
uv run dutch-tax-agent ingest -i ~/docs --year 2024
```

**Documents**: salary.pdf, bank_statement.pdf

**Result**:
- `box1_income_items`: [salary_item]
- `box3_asset_items`: [bank_account]
- `processed_documents`: [{id: "hash1", filename: "salary.pdf"}, {id: "hash2", filename: "bank_statement.pdf"}]

### Run 2: Incremental
```bash
cp broker_statement.pdf ~/docs
uv run dutch-tax-agent ingest -i ~/docs -t tax2024-abc123
```

**New Documents**: broker_statement.pdf (salary.pdf and bank_statement.pdf skipped via deduplication)

**Flow**:
1. ✅ Deduplication: Only broker_statement.pdf is new
2. ✅ Parse broker_statement.pdf
3. ✅ Scrub PII from broker_statement.pdf
4. ✅ Update state with scrubbed document
5. ✅ Resume graph
6. ✅ HITL routes to dispatcher (loop)
7. ✅ Extract: [broker_investment]
8. ✅ Validate: [validated_broker_investment]
9. ✅ Aggregate: **Append** to existing items
10. ✅ Reducer: Recalculate totals

**Result**:
- `box1_income_items`: [salary_item]  # Unchanged
- `box3_asset_items`: [bank_account, broker_investment]  # **Appended**
- `processed_documents`: [...previous..., {id: "hash3", filename: "broker_statement.pdf"}]
- `box3_total_assets_jan1`: **Recalculated** (sum of both accounts)

## Security Guarantee

**Zero-Trust Policy Maintained:**

1. ✅ Every new PDF is parsed independently
2. ✅ Every new document is scrubbed independently
3. ✅ Failed scrubbing → document excluded
4. ✅ No raw text stored in state after aggregation (cleared at line 546)
5. ✅ Only structured data persists in checkpoint

## Verification

You can verify this works by:

```bash
# Test incremental ingestion
uv run dutch-tax-agent ingest -i ~/docs --year 2024
# Note session ID

uv run dutch-tax-agent status -t <session-id>
# Check Box 1 and Box 3 totals

# Add more documents
cp new_document.pdf ~/docs
uv run dutch-tax-agent ingest -i ~/docs -t <session-id>

uv run dutch-tax-agent status -t <session-id>
# Verify totals increased (old + new)
```

## Fix Applied

**Issue Found**: `box1_income_items` and `box3_asset_items` were not using the `add` reducer, so they would be replaced rather than accumulated.

**Fix Applied**: Added `Annotated[list, add]` to both fields in `state.py`:

```python
# Before (would replace)
box1_income_items: list[Box1Income] = Field(...)
box3_asset_items: list[Box3Asset] = Field(...)

# After (accumulates)
box1_income_items: Annotated[list[Box1Income], add] = Field(...)
box3_asset_items: Annotated[list[Box3Asset], add] = Field(...)
```

Now incremental ingestion will properly accumulate items across multiple runs! ✅

