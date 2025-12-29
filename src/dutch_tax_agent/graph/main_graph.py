"""Main LangGraph orchestration with Map-Reduce pattern.

This module only contains graph construction logic. All nodes are defined
in their respective modules under graph/nodes/.
"""

import logging
import os

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END

from dutch_tax_agent.config import settings
from dutch_tax_agent.graph.agents import (
    dutch_parser_agent,
    investment_broker_parser_agent,
    revolut_parser_agent,
    salary_parser_agent,
)
from dutch_tax_agent.graph.nodes import (
    aggregate_extraction_node,
    dispatcher_node,
    hitl_control_node,
    reducer_node,
    validator_node,
)
from dutch_tax_agent.graph.nodes.box3.actual_return import actual_return_node
from dutch_tax_agent.graph.nodes.box3.comparison import comparison_node
from dutch_tax_agent.graph.nodes.box3.start_box3 import start_box3_node
from dutch_tax_agent.graph.nodes.box3.statutory_calculation import statutory_calculation_node
from dutch_tax_agent.schemas.state import TaxGraphState

logger = logging.getLogger(__name__)

# Store context managers to keep database connections alive
_active_checkpointer_contexts = []


def get_active_checkpointer_contexts():
    """Get the list of active checkpointer context managers.
    
    This is primarily for testing purposes to verify that context managers
    are being stored and not garbage collected.
    
    Returns:
        List of active context managers
    """
    return _active_checkpointer_contexts


def create_checkpointer():
    """Create a checkpointer based on configuration.
    
    Returns:
        Checkpointer instance (MemorySaver, SqliteSaver, or PostgresSaver)
    """
    if not settings.enable_checkpointing:
        logger.info("Checkpointing disabled")
        return None
    
    backend = settings.checkpoint_backend
    
    if backend == "memory":
        logger.info("Using MemorySaver for checkpointing (development mode)")
        return MemorySaver()
    
    elif backend == "sqlite":
        logger.info(f"Using SqliteSaver for checkpointing: {settings.checkpoint_db_path}")
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
            # Resolve path to expand ~ and get absolute path
            db_path = settings.checkpoint_db_path.expanduser().resolve()
            # Ensure parent directory exists
            db_path.parent.mkdir(parents=True, exist_ok=True)
            # from_conn_string returns a context manager, we need to enter it to get the instance
            # Store the context manager to keep the connection alive
            # Use absolute path string to ensure SQLite can create the file
            cm = SqliteSaver.from_conn_string(str(db_path))
            instance = cm.__enter__()
            # Store context manager to prevent garbage collection and connection closure
            _active_checkpointer_contexts.append(cm)
            return instance
        except ImportError:
            logger.warning(
                "SqliteSaver not available. Install with: uv add langgraph-checkpoint-sqlite. "
                "Falling back to MemorySaver."
            )
            return MemorySaver()
    
    elif backend == "postgres":
        logger.info("Using PostgresSaver for checkpointing")
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
            # This requires POSTGRES_URI in environment
            postgres_uri = os.getenv("POSTGRES_URI")
            if not postgres_uri:
                raise ValueError("POSTGRES_URI environment variable required for postgres backend")
            # from_conn_string returns a context manager, we need to enter it to get the instance
            # Store the context manager to keep the connection alive
            cm = PostgresSaver.from_conn_string(postgres_uri)
            instance = cm.__enter__()
            # Store context manager to prevent garbage collection and connection closure
            _active_checkpointer_contexts.append(cm)
            return instance
        except ImportError:
            logger.warning(
                "PostgresSaver not available. Install with: uv add langgraph-checkpoint-postgres. "
                "Falling back to MemorySaver."
            )
            return MemorySaver()
    
    else:
        logger.warning(f"Unknown checkpoint backend: {backend}. Using MemorySaver.")
        return MemorySaver()


def create_tax_graph() -> StateGraph:
    """Create the main tax processing graph with HITL support.
    
    Graph flow:
    1. START -> dispatcher (routes documents via Command + Send)
    2. dispatcher -> parser agents (parallel via Send API in Command)
    3. parser agents -> validators (parallel)
    4. validators -> aggregator (collects results)
    5. aggregator -> reducer (calculates totals)
    6. reducer -> hitl_control (HITL pause/resume point)
    7. hitl_control -> dispatcher (loop) OR start_box3 (calculate) OR END (pause)
    8. start_box3 -> statutory_calculation (with optimization)
                 -> actual_return (with optimization, parallel branch)
    9. statutory_calculation + actual_return -> comparison -> complete
    
    Returns:
        Compiled StateGraph
    """
    logger.info("Creating main tax processing graph with HITL support")

    # Create the main graph
    graph = StateGraph(TaxGraphState)

    # Add nodes
    graph.add_node("dispatcher", dispatcher_node)
    
    # Parser agents (called via Send from dispatcher's Command)
    graph.add_node("dutch_parser", dutch_parser_agent)
    graph.add_node("investment_broker_parser", investment_broker_parser_agent)
    graph.add_node("revolut_parser", revolut_parser_agent)
    graph.add_node("salary_parser", salary_parser_agent)
    
    # Validator (processes results from parsers)
    graph.add_node("validator", validator_node)
    
    # Aggregation and reduction
    graph.add_node("aggregate", aggregate_extraction_node)
    graph.add_node("reducer", reducer_node)
    
    # HITL control node (pause/resume point)
    graph.add_node("hitl_control", hitl_control_node)
    
    # Box 3 calculation nodes
    graph.add_node("start_box3", start_box3_node)
    graph.add_node("statutory_calculation", statutory_calculation_node)
    graph.add_node("actual_return", actual_return_node)
    # Use defer=True to ensure comparison only runs once after both branches complete
    graph.add_node("comparison", comparison_node, defer=True)

    # Define edges
    graph.add_edge(START, "dispatcher")
    
    # Dispatcher now uses Command with Send objects - no conditional edge needed
    # The Command's goto parameter contains the Send objects for parallel routing
    
    # Parser agents output goes to validator
    graph.add_edge("dutch_parser", "validator")
    graph.add_edge("investment_broker_parser", "validator")
    graph.add_edge("revolut_parser", "validator")
    graph.add_edge("salary_parser", "validator")
    
    # Validator results go to aggregator
    graph.add_edge("validator", "aggregate")
    
    # Aggregator goes to reducer (documents cleared during aggregation)
    graph.add_edge("aggregate", "reducer")
    
    # Reducer goes to HITL control (pause/resume point)
    graph.add_edge("reducer", "hitl_control")
    
    # HITL control uses Command for routing:
    # - goto="dispatcher" (loop for more documents)
    # - goto="start_box3" (proceed to calculation)
    # - goto=END (pause and wait)
    
    # Branch 1: Statutory Calculation (includes optimization)
    graph.add_edge("start_box3", "statutory_calculation")
    
    # Branch 2: Actual Return (includes optimization, parallel)
    graph.add_edge("start_box3", "actual_return")
    
    # Join: Both branches feed into comparison
    # The defer=True parameter ensures comparison only runs once after both branches complete
    graph.add_edge("statutory_calculation", "comparison")
    graph.add_edge("actual_return", "comparison")
    
    # Comparison completes the flow
    graph.add_edge("comparison", END)

    logger.info("Main tax graph created successfully with HITL support")

    # Compile with checkpointer
    checkpointer = create_checkpointer()
    if checkpointer:
        logger.info("Compiling graph with checkpointing enabled")
        # Use interrupt_before for hitl_control so the graph pauses BEFORE this node executes
        # When we update state and resume, hitl_control will re-execute with the new state
        return graph.compile(
            checkpointer=checkpointer,
            interrupt_before=["hitl_control"]
        )
    else:
        logger.info("Compiling graph without checkpointing")
        return graph.compile()


