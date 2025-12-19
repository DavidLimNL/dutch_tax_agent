"""Box 3 calculation nodes for the main graph.

Each module contains both the LangGraph node and its calculation logic.
"""

from dutch_tax_agent.graph.nodes.box3.actual_return import actual_return_node
from dutch_tax_agent.graph.nodes.box3.comparison import comparison_node
from dutch_tax_agent.graph.nodes.box3.fictional_yield import fictional_yield_node
from dutch_tax_agent.graph.nodes.box3.start_box3 import start_box3_node

__all__ = [
    "start_box3_node",
    "fictional_yield_node",
    "actual_return_node",
    "comparison_node",
]

