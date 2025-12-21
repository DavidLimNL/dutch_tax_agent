# Execution Flow Tracing Guide

## How to Trace Execution from `graph.invoke()`

When you call `self.graph.invoke(initial_state)` at line 102 in `main.py`, here's exactly where execution goes:

## 📍 Execution Flow Map

```
main.py:102
  └─> graph.invoke(initial_state)
       │
       ├─> START (LangGraph entry point)
       │
      ├─> dispatcher_node (graph/nodes/dispatcher.py:92)
      │   ├─> classify_document() for each doc
      │   ├─> Creates Send objects for parallel routing
      │   └─> Returns: Command(update={...}, goto=[Send(...), Send(...)])
       │
       ├─> [PARALLEL EXECUTION via Send API]
       │   │
       │   ├─> dutch_parser_agent (graph/agents/dutch_parser.py:17)
       │   │   └─> Returns: dict with extracted_data
       │   │
       │   ├─> us_broker_parser_agent (graph/agents/us_broker_parser.py:17)
       │   │   └─> Returns: dict with extracted_data
       │   │
       │   └─> salary_parser_agent (graph/agents/salary_parser.py:17)
       │       └─> Returns: dict with extracted_data
       │
       ├─> validator_node (graph/nodes/validators.py:12)
       │   ├─> Validates each extraction result
       │   ├─> Converts currency (tools/currency.py)
       │   └─> Returns: validated_results (accumulated in state)
       │
       ├─> aggregate_extraction_node (graph/nodes/aggregator.py:12)
       │   ├─> Reads from state.validated_results
       │   ├─> Collects all validated items
       │   └─> Returns: box1_income_items, box3_asset_items
       │
      ├─> reducer_node (graph/nodes/reducer.py:13)
      │   ├─> Calculates totals
      │   ├─> Validates completeness
      │   ├─> Determines routing based on validation/assets
      │   └─> Returns: Command(update={...}, goto="start_box3" | END)
       │
       ├─> [IF VALID] start_box3_node (graph/nodes/box3/start_box3.py)
       │   └─> Triggers parallel Box 3 calculations
       │
       ├─> [PARALLEL EXECUTION]
       │   │
       │   ├─> statutory_calculation_node (graph/nodes/box3/statutory_calculation.py)
       │   │   ├─> calculate_statutory_tax() (Savings Variant / Legacy for 2022)
       │   │   └─> optimize_partner_allocation() (fiscal partner optimization, if applicable)
       │   │
       │   └─> actual_return_node (graph/nodes/box3/actual_return.py)
       │       ├─> calculate_actual_return() (Hoge Raad method)
       │       └─> optimize_partner_allocation() (fiscal partner optimization, if applicable)
       │
       ├─> comparison_node (graph/nodes/box3/comparison.py)
       │   └─> compare_box3_methods() (compares statutory vs actual return)
       │
       └─> END (returns final_state to main.py:102)
```

## 🔍 Methods to Trace Execution

### Method 1: Use LangGraph Streaming (Recommended)

Replace `invoke()` with `stream()` to see each step:

```python
# In main.py, replace line 102:
for event in self.graph.stream(initial_state):
    node_name = list(event.keys())[0] if event else "unknown"
    console.print(f"[cyan]→ Executing: {node_name}[/cyan]")
    logger.info(f"Graph step: {node_name}")

# Get final state
final_state = None
for event in self.graph.stream(initial_state):
    final_state = list(event.values())[0]
```

### Method 2: Enable LangSmith Tracing

With `LANGSMITH_TRACING=true` in your `.env`, you can:
1. Go to https://smith.langchain.com (or EU endpoint)
2. See a visual graph of execution
3. Inspect inputs/outputs of each node
4. See timing and token usage

### Method 3: Add Logging to Each Node

Each node already has logging. Set `LOG_LEVEL=DEBUG` in `.env`:

```bash
LOG_LEVEL=DEBUG
```

Then you'll see:
```
INFO: Creating main tax processing graph
INFO: Dispatching 3 documents
INFO: Dutch parser processing bank_statement.pdf
INFO: Validating extraction result from bank_statement.pdf
...
```

### Method 4: Use Python Debugger

Add breakpoints:

```python
import pdb

# In any node function:
def dispatcher_node(state: TaxGraphState) -> dict:
    pdb.set_trace()  # Execution pauses here
    # ... rest of function
    # Returns dict with classified_documents
```

### Method 5: Print State at Each Step

Modify `create_tax_graph()` to add state inspection:

```python
def create_tax_graph() -> StateGraph:
    graph = StateGraph(TaxGraphState)
    
    # Add a debug wrapper
    def debug_node(node_func):
        def wrapper(state):
            logger.info(f"Entering {node_func.__name__}")
            logger.debug(f"State keys: {state.model_dump().keys()}")
            result = node_func(state)
            logger.info(f"Exiting {node_func.__name__}")
            return result
        return wrapper
    
    graph.add_node("dispatcher", debug_node(dispatcher_node))
    # ... rest of nodes
```

## 📊 Visual Execution Graph

The graph structure is defined in `graph/main_graph.py:121-189`:

```python
START
  ↓
dispatcher (classifies documents, returns Command with Send objects)
  ↓
[dutch_parser, us_broker_parser, salary_parser]  ← Parallel (via Command's Send objects)
  ↓
validator (validates & normalizes, accumulates in state.validated_results)
  ↓
aggregate (reads from state.validated_results, collects results)
  ↓
reducer (calculates totals, returns Command with routing decision)
  ├─→ start_box3 (if valid & has assets)
  │     ├─→ statutory_calculation_node (Savings Variant / Legacy + optimization)
  │     ├─→ actual_return_node (parallel - Hoge Raad method + optimization)
  │     └─→ comparison_node (compares both methods)
  │
  └─→ END (if quarantine or no assets)
```

## 🐛 Debugging Tips

1. **Check State Between Nodes**: Add logging in each node to see state changes
2. **Use LangSmith**: Best visual tool for understanding execution
3. **Stream Mode**: Use `stream()` instead of `invoke()` to see step-by-step
4. **Exception Handling**: Wrap `invoke()` in try/except to catch node failures
5. **State Inspection**: Print `state.model_dump()` at any point to see current state

## 📝 Key Files to Understand

- **Graph Definition**: `graph/main_graph.py` - `create_tax_graph()`
- **Node Functions**: `graph/nodes/*.py` - Each node implementation
- **Parser Agents**: `graph/agents/*.py` - Document parsers
- **Box 3 Nodes**: `graph/nodes/box3/*.py` - Box 3 calculation nodes (self-contained)
  - `statutory_calculation.py` - Savings Variant (2023-2025) and Legacy (2022) + fiscal partner optimization
  - `actual_return.py` - Hoge Raad actual return method + fiscal partner optimization
  - `optimization.py` - Fiscal partner allocation optimization function (called by calculation nodes)
  - `comparison.py` - Method comparison and recommendation
- **Tax Tools**: `tools/tax_credits.py` - General Tax Credit (AHK) calculation

## 🎯 Quick Reference

| Line | File | What Happens |
|------|------|--------------|
| 102 | `main.py` | `graph.invoke()` called |
| 76 | `graph/main_graph.py` | START → dispatcher |
| 92 | `graph/nodes/dispatcher.py` | Classifies documents, returns Command with Send objects |
| 17 | `graph/agents/*.py` | Extract data (parallel) |
| 12 | `graph/nodes/validators.py` | Validate & normalize |
| 12 | `graph/nodes/aggregator.py` | Aggregate results from state.validated_results |
| 13 | `graph/nodes/reducer.py` | Calculate totals, returns Command with routing |
| - | `graph/nodes/box3/start_box3.py` | Start Box 3 calculations |
| - | `graph/nodes/box3/statutory_calculation.py` | Calculate statutory tax (Savings Variant / Legacy) + optimize partner allocation |
| - | `graph/nodes/box3/actual_return.py` | Calculate actual return (Hoge Raad method) + optimize partner allocation |
| - | `graph/nodes/box3/comparison.py` | Compare methods |
| END | - | Return final state |


