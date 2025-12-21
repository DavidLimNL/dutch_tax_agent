# LangGraph Checkpointing & State Management

## Overview

The Dutch Tax Agent implements LangGraph checkpointing to:
1. **Reduce token usage** by clearing document text after extraction
2. **Enable human-in-the-loop** workflows (e.g., quarantine review)
3. **Support pause/resume** for long-running processes
4. **Provide fault tolerance** (resume from failures)
5. **Create audit trail** (inspect state at any point)

## Architecture

### State Lifecycle

```mermaid
graph LR
    A[Documents Loaded] --> B[Dispatcher]
    B --> C[Parser Agents]
    C --> D[Validators]
    D --> E[Aggregator]
    E --> G[Reducer]
    G --> H[Box 3 Calculations]
    
    style E fill:#f9f,stroke:#333,stroke-width:2px
    
    note1[Documents cleared during aggregation]
    E -.-> note1
```

### Memory Optimization

**Before Cleanup (at Aggregator Input):**
- State contains: 
  - `documents` (full scrubbed text)
  - `classified_documents` (contains duplicate `doc_text` - same content!)
  - `extraction_results`, `box1_income_items`, `box3_asset_items`
- Total size: ~20-200KB per document (depending on size, **duplicated** in both fields)

**After Cleanup (at Aggregator Output):**
- State contains: `extraction_results`, `box1_income_items`, `box3_asset_items` (structured data only)
- Total size: ~1-5KB (90-95% reduction)

The `aggregate_extraction_node` clears both `documents` and `classified_documents` at the end of its execution. 

**Why both?**
- `documents`: Full scrubbed document text (no longer needed after extraction)
- `classified_documents`: Contains duplicate `doc_text` that was only needed for routing. Parser agents receive data via `Send` objects, not from state, so this is safe to clear.

This happens automatically as part of the aggregation step, eliminating the need for a separate cleanup node.

## Configuration

### Environment Variables

Add to your `.env` file:

```bash
# Checkpointing Configuration
ENABLE_CHECKPOINTING=true
CHECKPOINT_BACKEND=memory  # Options: memory, sqlite, postgres
CHECKPOINT_DB_PATH=./data/checkpoints.db  # For sqlite backend
```

### Backend Options

#### 1. MemorySaver (Default - Development)

```python
ENABLE_CHECKPOINTING=true
CHECKPOINT_BACKEND=memory
```

**Pros:**
- No setup required
- Fast
- Good for development

**Cons:**
- Not persisted across restarts
- Limited to single process

#### 2. SQLite (Recommended - Production)

```bash
# Install the package
uv add langgraph-checkpoint-sqlite

# Configure
ENABLE_CHECKPOINTING=true
CHECKPOINT_BACKEND=sqlite
CHECKPOINT_DB_PATH=./data/checkpoints.db
```

**Pros:**
- Persisted to disk
- No external dependencies
- Good for single-server deployments

**Cons:**
- Not suitable for distributed systems

#### 3. PostgreSQL (Enterprise)

```bash
# Install the package
uv add langgraph-checkpoint-postgres

# Configure
ENABLE_CHECKPOINTING=true
CHECKPOINT_BACKEND=postgres
POSTGRES_URI=postgresql://user:pass@localhost:5432/dutch_tax_agent
```

**Pros:**
- Distributed system support
- High availability
- Suitable for multi-server deployments

**Cons:**
- Requires PostgreSQL server

## Usage

### Basic Invocation with Checkpointing

```python
from dutch_tax_agent import DutchTaxAgent

# Create agent (thread_id auto-generated)
agent = DutchTaxAgent(tax_year=2024)

# Process documents (automatically uses checkpointing)
result = agent.process_documents(pdf_files)

print(f"Thread ID: {agent.thread_id}")  # Save this for later
```

### Resume from Checkpoint

```python
from dutch_tax_agent import DutchTaxAgent

# Resume using saved thread_id
agent = DutchTaxAgent(tax_year=2024, thread_id="tax2024-abc123")

# Will resume from last checkpoint
result = agent.process_documents(pdf_files)
```

### Inspect Checkpoint History

```python
from dutch_tax_agent.checkpoint_utils import list_checkpoints, print_checkpoint_history

# Get checkpointer from graph
graph = create_tax_graph()
checkpointer = graph.checkpointer

# List checkpoints
checkpoints = list_checkpoints(checkpointer, thread_id="tax2024-abc123")

for cp in checkpoints:
    print(f"Step {cp['step']}: {cp['source']}")

# Or pretty-print
print_checkpoint_history(checkpointer, "tax2024-abc123")
```

### Inspect State at Specific Node

```python
from dutch_tax_agent.checkpoint_utils import inspect_state_at_node

# Get state after aggregation (before cleanup)
state = inspect_state_at_node(checkpointer, "tax2024-abc123", "aggregate")

print(f"Documents before cleanup: {len(state['documents'])}")
print(f"Box1 items: {len(state['box1_income_items'])}")
print(f"Box3 items: {len(state['box3_asset_items'])}")
```

## Human-in-the-Loop Workflows

### Example: Quarantine Review

```python
from dutch_tax_agent.checkpoint_utils import resume_from_checkpoint

# 1. Initial run (will pause at quarantine if needed)
agent = DutchTaxAgent(tax_year=2024)
result = agent.process_documents(pdf_files)

# Check if human review needed
if result.requires_human_review:
    print("⚠️  Human review required!")
    print(f"Thread ID: {agent.thread_id}")
    print(f"Issues: {result.validation_errors}")
    
    # 2. Human reviews and provides corrections
    corrections = {
        "box3_asset_items": [
            # ... corrected items
        ],
        "requires_human_review": False,
    }
    
    # 3. Resume with corrections
    final_result = resume_from_checkpoint(
        graph=agent.graph,
        thread_id=agent.thread_id,
        updates=corrections
    )
    
    print("✓ Processing resumed and completed!")
```

## Command-Line Usage

```bash
# Process with auto-generated thread ID
uv run dutch-tax-agent --input-dir ./docs --year 2024

# Process with specific thread ID (for resuming)
uv run dutch-tax-agent --input-dir ./docs --year 2024 --thread-id tax2024-abc123

# Process without checkpointing (not recommended)
ENABLE_CHECKPOINTING=false uv run dutch-tax-agent --input-dir ./docs --year 2024
```

## Token Usage Optimization

### Before Checkpointing + Cleanup

Each node invocation would serialize:
```json
{
  "documents": [
    {
      "doc_id": "doc1",
      "filename": "salary.pdf",
      "scrubbed_text": "... 50,000+ characters ..."
    }
  ],
  "classified_documents": [
    {
      "doc_id": "doc1",
      "doc_text": "... 50,000+ characters ...",  // Duplicate!
      "filename": "salary.pdf",
      "target_node": "salary_parser",
      "classification": {...}
    }
  ],
  "extraction_results": [...],
  "box1_income_items": [...],
  "box3_asset_items": [...]
}
```

**Estimated tokens per checkpoint:** 20,000-100,000 tokens (document text duplicated in both fields!)

### After Checkpointing + Cleanup

After the `aggregate_extraction_node` (which clears both `documents` and `classified_documents`):
```json
{
  "documents": [],  // Cleared!
  "classified_documents": [],  // Cleared! (duplicate text removed)
  "extraction_results": [...],
  "box1_income_items": [...],
  "box3_asset_items": [...]
}
```

**Estimated tokens per checkpoint:** 500-2,000 tokens

**Token savings:** 90-98% reduction in state size! (Even better because we clear duplicate text)

## Debugging

### Enable Verbose Logging

```python
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dutch_tax_agent")
logger.setLevel(logging.DEBUG)
```

### Inspect Checkpoints

```python
from dutch_tax_agent.checkpoint_utils import get_checkpoint_state

# Get latest state
state = get_checkpoint_state(checkpointer, thread_id="tax2024-abc123")

# Check what's in state
print("State keys:", list(state.keys()))
print("Documents:", len(state.get("documents", [])))
print("Box1 items:", len(state.get("box1_income_items", [])))
```

### Visualize Graph Execution

```python
# Enable streaming to see node-by-node execution
for event in agent.graph.stream(initial_state, config=config):
    node_name = list(event.keys())[0]
    print(f"→ Executing: {node_name}")
```

## Best Practices

1. **Always use thread_ids in production**
   - Save thread_id to user session/database
   - Use for resuming and debugging

2. **Enable checkpointing by default**
   - Disable only for testing or one-off scripts

3. **Use SQLite for production deployments**
   - MemorySaver is only for development

4. **Monitor checkpoint sizes**
   - Ensure document cleanup in aggregator is working
   - Check database growth over time

5. **Implement cleanup policies**
   - Delete old checkpoints after N days
   - Archive completed sessions

## Future Enhancements

- [ ] Add checkpoint cleanup utilities
- [ ] Implement checkpoint retention policies
- [ ] Add checkpoint export/import for debugging
- [ ] Create web UI for checkpoint inspection
- [ ] Add metrics/monitoring for checkpoint performance

## Related Documentation

- [LangGraph Checkpointing Docs](https://langchain-ai.github.io/langgraph/how-tos/persistence/)
- [Architecture Overview](./architecture.md)
- [Execution Flow](./execution_flow.md)

