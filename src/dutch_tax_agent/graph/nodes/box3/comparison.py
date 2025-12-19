"""Comparison node and logic for Box 3 calculation methods.

This module contains both the LangGraph node and the comparison logic.
"""

import logging

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langsmith import traceable

from dutch_tax_agent.config import settings
from dutch_tax_agent.schemas.state import TaxGraphState
from dutch_tax_agent.schemas.tax_entities import Box3Calculation

logger = logging.getLogger(__name__)


@traceable(name="Box 3 Comparison Agent")
def compare_box3_methods(
    fictional_yield: Box3Calculation,
    actual_return: Box3Calculation,
) -> dict:
    """Compare the two Box 3 calculation methods and provide recommendation.
    
    Args:
        fictional_yield: Result from fictional yield method
        actual_return: Result from actual return method
        
    Returns:
        Dict with:
            - difference_eur: Tax difference
            - recommended_method: Which method to use
            - reasoning: Natural language explanation
    """
    logger.info("Comparing Box 3 calculation methods")

    difference = fictional_yield.tax_owed - actual_return.tax_owed

    logger.info(
        f"Tax comparison: Fictional Yield = €{fictional_yield.tax_owed:,.2f}, "
        f"Actual Return = €{actual_return.tax_owed:,.2f}, "
        f"Difference = €{difference:,.2f}"
    )

    # Determine recommendation
    if actual_return.tax_owed < fictional_yield.tax_owed:
        recommended = "actual_return"
        savings = difference
    else:
        recommended = "fictional_yield"
        savings = -difference

    # Generate natural language explanation using LLM
    llm = ChatOpenAI(model=settings.openai_model, temperature=0.3)

    prompt = f"""You are a Dutch tax advisor. Compare these two Box 3 calculation methods and explain the recommendation to the taxpayer.

Fictional Yield Method (Old Law):
- Total wealth: €{fictional_yield.net_wealth_jan1:,.2f}
- Deemed income: €{fictional_yield.deemed_income:,.2f}
- Tax owed: €{fictional_yield.tax_owed:,.2f}

Actual Return Method (New Law):
- Total wealth: €{actual_return.net_wealth_jan1:,.2f}
- Actual gains: €{actual_return.actual_gains:,.2f}
- Tax owed: €{actual_return.tax_owed:,.2f}

Difference: €{abs(difference):,.2f}
Recommended: {recommended}

Provide a clear, professional explanation in 2-3 sentences covering:
1. Which method results in lower tax
2. What documentation would be needed for the actual return method
3. The potential savings/cost

Use Dutch tax terminology where appropriate (Box 3, vermogensrendementsheffing, etc.).
"""

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        reasoning = response.content.strip()

        logger.info(f"Generated comparison reasoning: {reasoning[:100]}...")

        return {
            "difference_eur": difference,
            "recommended_method": recommended,
            "reasoning": reasoning,
            "potential_savings": savings if savings > 0 else 0,
        }

    except Exception as e:
        logger.error(f"Failed to generate comparison reasoning: {e}")

        # Fallback to simple text
        fallback_reasoning = (
            f"The {recommended} method results in €{abs(difference):,.2f} "
            f"{'less' if savings > 0 else 'more'} tax. "
            f"{'Consider using the actual return method if you have proper documentation of realized gains.' if recommended == 'actual_return' else 'The fictional yield method is simpler and requires less documentation.'}"
        )

        return {
            "difference_eur": difference,
            "recommended_method": recommended,
            "reasoning": fallback_reasoning,
            "potential_savings": savings if savings > 0 else 0,
        }


def comparison_node(state: TaxGraphState) -> dict:
    """LangGraph node that compares both Box 3 calculation methods.
    
    Args:
        state: Main graph state with both calculation results
        
    Returns:
        Dict with comparison results and final status
    """
    logger.info("Running Box 3 comparison node")

    if not state.box3_fictional_yield_result or not state.box3_actual_return_result:
        logger.error("Cannot compare - one or both calculations missing")
        return {
            "status": "complete",
            "potential_savings_eur": 0.0,
            "recommendation_reasoning": "Comparison failed: missing calculation results",
        }

    comparison = compare_box3_methods(
        state.box3_fictional_yield_result,
        state.box3_actual_return_result,
    )

    return {
        "status": "complete",
        "potential_savings_eur": comparison["difference_eur"] if comparison["difference_eur"] > 0 else None,
        "recommendation_reasoning": comparison["reasoning"],
    }

