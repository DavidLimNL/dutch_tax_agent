# Human-in-the-Loop (HITL) Workflow

The Dutch Tax Agent supports a human-in-the-loop workflow that allows you to iteratively process documents and review data before triggering tax calculations.

## Features

- **Incremental Document Processing**: Add documents to a thread over time
- **Document Management**: Remove or replace documents as needed
- **Thread Persistence**: Resume processing after stopping the application
- **Review Before Calculate**: Inspect extracted data before running calculations
- **SQLite Checkpointing**: All state persists to disk automatically

## Basic Workflow

### 1. Create a New Thread and Ingest Documents

```bash
# Process initial documents
dutch-tax-agent ingest --input-dir ~/my_tax_docs/ --year 2024
```

Output:
```
✓ Created thread: tax2024-abc123def456
✓ Processed 2 documents
⏸  Paused - awaiting command
```

The thread ID (e.g., `tax2024-abc123def456`) is used for all subsequent operations.

### 2. Check Thread Status

```bash
# View current state
dutch-tax-agent status --thread-id tax2024-abc123def456
```

This displays:
- Documents processed
- Extracted Box 1 income
- Extracted Box 3 assets
- Validation warnings/errors
- Next available actions

### 3. Add More Documents

```bash
# Add newly discovered documents
cp additional_statement.pdf ~/my_tax_docs/
dutch-tax-agent ingest --input-dir ~/my_tax_docs/ --thread-id tax2024-abc123def456
```

The system automatically:
- Detects which documents are new (using SHA256 hashing)
- Skips already-processed documents
- Merges new extractions with existing data
- Recalculates totals

### 4. Remove Documents (Optional)

```bash
# Remove by document ID
dutch-tax-agent remove --thread-id tax2024-abc123def456 -d a1b2c3d4e5f6

# Remove by filename
dutch-tax-agent remove --thread-id tax2024-abc123def456 --filename wrong_statement.pdf

# Remove all documents (with confirmation)
dutch-tax-agent remove --thread-id tax2024-abc123def456 --all
```

The system automatically recalculates Box 1/3 totals after removal.

### 5. Calculate Taxes

```bash
# Trigger Box 3 calculations
dutch-tax-agent calculate --thread-id tax2024-abc123def456
```

This runs:
- Box 3 Fictional Yield (old law)
- Box 3 Actual Return (new law - Hoge Raad)
- Fiscal partner optimization (if enabled)
- Comparison and recommendation

## Advanced Usage

### List All Threads

```bash
# List active threads
dutch-tax-agent threads

# List all threads (including completed)
dutch-tax-agent threads --all
```

### Delete a Thread

```bash
# Delete thread (with confirmation)
dutch-tax-agent reset --thread-id tax2024-abc123def456

# Force delete (no confirmation)
dutch-tax-agent reset --thread-id tax2024-abc123def456 --force
```

### Disable Fiscal Partner

By default, the agent assumes you have a fiscal partner. To disable:

```bash
dutch-tax-agent ingest --input-dir ~/docs/ --year 2024 --no-fiscal-partner
```

## How It Works

### Graph Flow with HITL

```
START → dispatcher → parsers → validators → aggregator → reducer → HITL_CONTROL
                                                                          ↓
                                          ┌───────────────────────────────┤
                                          ↓                               ↓
                                    dispatcher (loop)              start_box3 (calculate)
                                          ↓                               ↓
                                    (more docs)                    (Box 3 calc)
                                          ↓                               ↓
                                    HITL_CONTROL                        END
                                          ↓
                                    (pause again)
```

The **HITL Control Node** acts as a decision point:
- `await_human`: Pause execution (wait for user command)
- `ingest_more`: Loop back to dispatcher (process new documents)
- `calculate`: Proceed to Box 3 calculation

### Checkpointing

The system uses **SqliteSaver** for persistent checkpointing:
- Database location: `~/.dutch_tax_agent/checkpoints.db`
- Thread registry: `~/.dutch_tax_agent/threads.json`
- Automatic state persistence after each node execution
- Resume from exact point after restart

### Document Deduplication

Documents are identified by SHA256 hash:
- Each PDF generates a unique hash
- Already-processed documents are automatically skipped
- Hash stored in checkpoint state

### State Management

The graph state includes:
- `processed_documents`: List of document metadata (ID, filename, hash, timestamp)
- `next_action`: Controls HITL routing (`await_human`, `ingest_more`, `calculate`)
- `box1_income_items`: Extracted income data
- `box3_asset_items`: Extracted asset data
- `box1_total_income`: Calculated total
- `box3_total_assets_jan1`: Calculated total

## Example: Complete Workflow

```bash
# Step 1: Initial ingestion
dutch-tax-agent ingest -i ~/tax2024/ -y 2024
# Output: Thread tax2024-abc123 created

# Step 2: Check what was extracted
dutch-tax-agent status -t tax2024-abc123
# Review Box 1 and Box 3 totals

# Step 3: Found more documents
cp ~/Downloads/Q4_statement.pdf ~/tax2024/
dutch-tax-agent ingest -i ~/tax2024/ -t tax2024-abc123
# Output: 1 new document processed

# Step 4: Wrong document was added
dutch-tax-agent status -t tax2024-abc123
# See document ID: a1b2c3d4e5f6
dutch-tax-agent remove -t tax2024-abc123 -d a1b2c3d4e5f6

# Step 5: Ready to calculate
dutch-tax-agent calculate -t tax2024-abc123
# Output: Box 3 comparison results

# Step 6: Review all threads
dutch-tax-agent threads
```

## Troubleshooting

### Thread Not Found
```
Error: Thread tax2024-abc123 not found
```
**Solution**: Check thread ID with `dutch-tax-agent threads`

### No New Documents
```
⚠️  No new documents found
```
**Cause**: All documents in the folder have already been processed.
**Solution**: This is normal behavior. Documents are deduplicated by hash.

### Cannot Resume After Restart
```
Error: Thread not found
```
**Cause**: Using MemorySaver instead of SqliteSaver
**Solution**: Ensure `CHECKPOINT_BACKEND=sqlite` in `.env` (default as of v0.2.0)

### Document Removal Not Recalculating
**Cause**: Bug in document manager
**Solution**: Check that document ID matches exactly (use `status` to see IDs)

## Configuration

### Environment Variables

```bash
# Checkpointing (required for HITL)
ENABLE_CHECKPOINTING=true
CHECKPOINT_BACKEND=sqlite  # Default
CHECKPOINT_DB_PATH=~/.dutch_tax_agent/checkpoints.db  # Default
```

### Thread Storage

Threads are stored in:
- **Checkpoints**: `~/.dutch_tax_agent/checkpoints.db` (SQLite)
- **Registry**: `~/.dutch_tax_agent/threads.json` (JSON)

To reset everything:
```bash
rm -rf ~/.dutch_tax_agent/
```

## Limitations

- **No concurrent threads**: Don't run multiple commands on the same thread simultaneously
- **No state merging**: Adding documents replaces `documents` list (old docs cleared from state, but metadata remains)
- **Document order**: Documents processed in filesystem order
- **No partial removal**: Can't remove individual line items, only entire documents

## Future Enhancements

Planned features for future releases:
- Interactive review mode (approve/reject extracted data)
- Document preview in CLI
- Export thread data to JSON/CSV
- Web UI for thread management
- Undo/redo operations
- Manual corrections to extracted values

