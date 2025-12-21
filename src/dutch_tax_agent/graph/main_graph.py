"""Main LangGraph orchestration with Map-Reduce pattern.

This module only contains graph construction logic. All nodes are defined
in their respective modules under graph/nodes/.
"""

import logging

from langgraph.graph import StateGraph, START, END

from dutch_tax_agent.graph.agents import (
    dutch_parser_agent,
    salary_parser_agent,
    us_broker_parser_agent,
)
from dutch_tax_agent.graph.nodes import (
    aggregate_extraction_node,
    dispatcher_node,
    reducer_node,
    validator_node,
)
from dutch_tax_agent.graph.nodes.box3.actual_return import actual_return_node
from dutch_tax_agent.graph.nodes.box3.comparison import comparison_node
from dutch_tax_agent.graph.nodes.box3.optimization import optimization_node
from dutch_tax_agent.graph.nodes.box3.start_box3 import start_box3_node
from dutch_tax_agent.graph.nodes.box3.statutory_calculation import statutory_calculation_node
from dutch_tax_agent.schemas.state import TaxGraphState

logger = logging.getLogger(__name__)


def create_tax_graph() -> StateGraph:
    """Create the main tax processing graph.
    
    Graph flow:
    1. START -> dispatcher (routes documents via Command + Send)
    2. dispatcher -> parser agents (parallel via Send API in Command)
    3. parser agents -> validators (parallel)
    4. validators -> aggregator (collects results)
    5. aggregator -> reducer (calculates totals, uses Command for routing)
    6. reducer -> start_box3 OR END (via Command based on validation/assets)
    7. start_box3 -> statutory_calculation -> optimization
                 -> actual_return (parallel branch)
    8. optimization + actual_return -> comparison -> complete
    
    Returns:
        Compiled StateGraph
    """
    logger.info("Creating main tax processing graph")

    # Create the main graph
    graph = StateGraph(TaxGraphState)

    # Add nodes
    graph.add_node("dispatcher", dispatcher_node)
    
    # Parser agents (called via Send from dispatcher's Command)
    graph.add_node("dutch_parser", dutch_parser_agent)
    graph.add_node("us_broker_parser", us_broker_parser_agent)
    graph.add_node("salary_parser", salary_parser_agent)
    
    # Validator (processes results from parsers)
    graph.add_node("validator", validator_node)
    
    # Aggregation and reduction
    graph.add_node("aggregate", aggregate_extraction_node)
    graph.add_node("reducer", reducer_node)
    
    # Box 3 calculation nodes
    graph.add_node("start_box3", start_box3_node)
    graph.add_node("statutory_calculation", statutory_calculation_node)
    graph.add_node("optimization", optimization_node)
    graph.add_node("actual_return", actual_return_node)
    graph.add_node("comparison", comparison_node)

    # Define edges
    graph.add_edge(START, "dispatcher")
    
    # Dispatcher now uses Command with Send objects - no conditional edge needed
    # The Command's goto parameter contains the Send objects for parallel routing
    
    # Parser agents output goes to validator
    graph.add_edge("dutch_parser", "validator")
    graph.add_edge("us_broker_parser", "validator")
    graph.add_edge("salary_parser", "validator")
    
    # Validator results go to aggregator
    graph.add_edge("validator", "aggregate")
    
    # Aggregator goes to reducer
    graph.add_edge("aggregate", "reducer")
    
    # Reducer now uses Command for routing - no conditional edge needed
    # The Command determines whether to go to "start_box3" or END based on validation/assets
    
    # Branch 1: Statutory Calculation -> Optimization
    graph.add_edge("start_box3", "statutory_calculation")
    graph.add_edge("statutory_calculation", "optimization")
    
    # Branch 2: Actual Return (Parallel)
    graph.add_edge("start_box3", "actual_return")
    
    # Join: Both branches feed into comparison
    graph.add_edge("optimization", "comparison")
    graph.add_edge("actual_return", "comparison")
    
    # Comparison completes the flow
    graph.add_edge("comparison", END)

    logger.info("Main tax graph created successfully")

    return graph.compile()


