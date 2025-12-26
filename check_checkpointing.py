#!/usr/bin/env python3
"""Diagnostic script to check checkpointing configuration and test database creation."""

import sys
from pathlib import Path
import os

print("=" * 80)
print("Checkpointing Diagnostic")
print("=" * 80)

# Check 1: Configuration
print("\n1. Checking configuration...")
try:
    from dutch_tax_agent.config import settings
    print(f"   ✓ Checkpointing enabled: {settings.enable_checkpointing}")
    print(f"   ✓ Backend: {settings.checkpoint_backend}")
    print(f"   ✓ DB path: {settings.checkpoint_db_path}")
    print(f"   ✓ DB path exists: {settings.checkpoint_db_path.exists()}")
    print(f"   ✓ Parent dir exists: {settings.checkpoint_db_path.parent.exists()}")
except Exception as e:
    print(f"   ✗ Error loading config: {e}")
    sys.exit(1)

# Check 2: SQLite package
print("\n2. Checking langgraph-checkpoint-sqlite package...")
try:
    from langgraph.checkpoint.sqlite import SqliteSaver
    print("   ✓ langgraph-checkpoint-sqlite is installed")
except ImportError as e:
    print(f"   ✗ langgraph-checkpoint-sqlite NOT installed: {e}")
    print("   → Install with: uv add langgraph-checkpoint-sqlite")
    sys.exit(1)

# Check 3: Try to create checkpointer
print("\n3. Testing checkpointer creation...")
try:
    from dutch_tax_agent.graph.main_graph import create_checkpointer
    checkpointer = create_checkpointer()
    if checkpointer is None:
        print("   ✗ Checkpointer is None (checkpointing disabled?)")
        sys.exit(1)
    
    checkpointer_type = type(checkpointer).__name__
    print(f"   ✓ Checkpointer created: {checkpointer_type}")
    
    if checkpointer_type == "MemorySaver":
        print("   ⚠️  WARNING: Using MemorySaver instead of SqliteSaver!")
        print("   → Check your CHECKPOINT_BACKEND setting")
    elif checkpointer_type == "SqliteSaver":
        print("   ✓ Using SqliteSaver (correct)")
    
except Exception as e:
    print(f"   ✗ Error creating checkpointer: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Check 4: Try to create graph
print("\n4. Testing graph creation...")
try:
    from dutch_tax_agent.graph import create_tax_graph
    graph = create_tax_graph()
    print("   ✓ Graph created successfully")
    
    if hasattr(graph, 'checkpointer'):
        print(f"   ✓ Graph has checkpointer: {type(graph.checkpointer).__name__}")
    else:
        print("   ⚠️  Graph does not have checkpointer attribute")
        
except Exception as e:
    print(f"   ✗ Error creating graph: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Check 5: Test database creation
print("\n5. Testing database file creation...")
db_path = settings.checkpoint_db_path
# Resolve the path properly
resolved_path = db_path.expanduser() if hasattr(db_path, 'expanduser') else Path(str(db_path).expanduser())
print(f"   DB path (raw): {db_path}")
print(f"   DB path (resolved): {resolved_path}")
print(f"   DB path (absolute): {resolved_path.resolve()}")

if resolved_path.exists():
    print(f"   ✓ Database file exists ({resolved_path.stat().st_size} bytes)")
    print(f"   ✓ Full path: {resolved_path.resolve()}")
else:
    print("   ⚠️  Database file does NOT exist yet")
    print("   → This is normal - SQLite creates the file on first write")
    print("   → The file will be created when you run a command that executes the graph")

# Check 6: Try a minimal graph execution
print("\n6. Testing minimal graph execution (this will create the DB if it works)...")
try:
    from dutch_tax_agent.schemas.state import TaxGraphState
    from dutch_tax_agent.checkpoint_utils import generate_thread_id
    
    thread_id = generate_thread_id(prefix="test")
    initial_state = TaxGraphState(
        documents=[],  # Empty to avoid LLM calls
        tax_year=2024,
    )
    config = {"configurable": {"thread_id": thread_id}}
    
    print(f"   Executing graph with thread_id: {thread_id}")
    result = graph.invoke(initial_state, config=config)
    print("   ✓ Graph executed successfully")
    
    # Check if DB was created
    resolved_path = db_path.expanduser() if hasattr(db_path, 'expanduser') else Path(str(db_path).expanduser())
    if resolved_path.exists():
        print(f"   ✓ Database file now exists! ({resolved_path.stat().st_size} bytes)")
        print(f"   ✓ Full path: {resolved_path.resolve()}")
    else:
        print("   ⚠️  Database file still not created")
        print("   → This might mean checkpointing is disabled or using MemorySaver")
        
except Exception as e:
    print(f"   ✗ Error executing graph: {e}")
    import traceback
    traceback.print_exc()
    # Don't exit - this might be expected if there are no documents

print("\n" + "=" * 80)
print("Diagnostic complete!")
print("=" * 80)

