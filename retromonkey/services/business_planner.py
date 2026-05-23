"""Business planner service — SWOT, projections, pricing strategy, risk analysis."""

import json
import logging
from datetime import datetime, timezone

from retromonkey.app import db
from retromonkey.services.llm_router import LLMRouter
from retromonkey.services.research import ResearchService

logger = logging.getLogger(__name__)


class BusinessPlannerService:
    """Generate comprehensive business plans for product niches."""

    def __init__(self, db_instance, llm_router=None):
        self.db = db_instance or db
        self.llm = llm_router or LLMRouter()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def generate_plan(
        self,
        niche: str,
        investment_budget: float,
    ) -> dict:
        """Generate a full business plan for a niche.

        Parameters
        ----------
        niche : str
            Product niche / keyword.
        investment_budget : float
            Available investment capital in AUD.

        Returns
        -------
        dict
            Keys: niche, budget, swot, pricing_strategy, projections (12-mo),
            risks, recommendations.
        """
        # Gather research
        research_svc = ResearchService(self.db, self.llm)
        research = research_svc.research_niche(niche, depth="deep")

        # Pricing strategy
        pricing = self._calculate_pricing_strategy(research, investment_budget)

        # 12-month projections
        projections = self._generate_projections(research, pricing, investment_budget)

        # SWOT + risk + recommendations via LLM
        plan_doc = self._generate_llm_plan(niche, research, pricing, projections, investment_budget)

        return {
            "niche": niche,
            "budget": investment_budget,
            "currency": "AUD",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "research_summary": {
                "niche_score": research.get("niche_score"),
                "competitor_count": research.get("competitor_count", 0),
                "margin_estimate": research.get("margin_estimate"),
                "recommendation": research.get("recommendation"),
            },
            "swot": plan_doc.get("swot", {}),
            "pricing_strategy": pricing,
            "projections": projections,
            "risks": plan_doc.get("risks", []),
            "recommendations": plan_doc.get("recommendations", []),
        }

    # ------------------------------------------------------------------
    # Pricing strategy
    # ------------------------------------------------------------------

    def _calculate_pricing_strategy(
        self,
        research: dict,
        budget: float,
    ) -> dict:
        """Calculate competitive pricing tiers based on research data."""
        competitors = research.get("competitors", [])
        margin = research.get("margin_estimate", 0.5)

        prices = [c["price"] for c in competitors if c.get("price", 0) > 0]

        if not prices:
            return {
                "strategy": "cost_plus",
                "estimated_cost": round(budget * 0.4, 2),
                "suggested_price": round(budget * 0.4 / max(0.01, 1 - margin), 2),
                "margin_target": round(margin * 100, 1),
                "note": "No competitor data available; using cost-plus model.",
            }

        avg_price = sum(prices) / len(prices)
        min_price = min(prices)
        max_price = max(prices)
        median_price = sorted(prices)[len(prices) // 2]

        # Estimated cost based on margin
        estimated_cost = avg_price * (1 - margin)

        # Suggest pricing tiers
        economy = round(max(min_price * 0.9, estimated_cost * 1.2), 2)
        competitive = round(avg_price * 0.95, 2)
        premium = round(median_price * 1.1, 2)

        return {
            "strategy": "competitive",
            "estimated_cost": round(estimated_cost, 2),
            "market_avg_price": round(avg_price, 2),
            "market_min_price": round(min_price, 2),
            "market_max_price": round(max_price, 2),
            "pricing_tiers": {
                "economy": economy,
                "competitive": competitive,
                "premium": premium,
            },
            "margin_target": round(margin * 100, 1),
            "recommended_tier": "competitive",
        }

    # ------------------------------------------------------------------
    # Financial projections
    # ------------------------------------------------------------------

    def _generate_projections(
        self,
        research: dict,
        pricing: dict,
        budget: float,
    ) -> list[dict]:
        """Generate 12-month revenue, cost, and profit projections."""
        niche_score = research.get("niche_score", 50)
        margin = research.get("margin_estimate", 0.5)

        # Determine base monthly units from niche score
        # Higher score = more optimistic
        base_units = int(10 + (niche_score / 100) * 40)  # 10-50 units/month

        suggested_price = pricing.get("pricing_tiers", {}).get("competitive", 0)
        if not suggested_price:
            suggested_price = pricing.get("suggested_price", 25.0)

        estimated_cost = pricing.get("estimated_cost", suggested_price * (1 - margin))

        # Apply growth curve: slow start, ramp up
        growth_rates = [0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15, 1.2]

        projections = []
        for month, growth in enumerate(growth_rates, 1):
            units = int(base_units * growth)
            revenue = round(units * suggested_price, 2)
            cogs = round(units * estimated_cost, 2)
            fees = round(revenue * 0.13, 2)  # ~13% marketplace fees
            shipping = round(units * 5.0, 2)  # ~$5/unit shipping
            overhead = round(budget * 0.02, 2)  # 2% of budget monthly overhead
            total_cost = round(cogs + fees + shipping + overhead, 2)
            profit = round(revenue - total_cost, 2)

            projections.append({
                "month": month,
                "projected_units": units,
                "revenue": revenue,
                "cogs": cogs,
                "fees": fees,
                "shipping": shipping,
                "overhead": overhead,
                "total_cost": total_cost,
                "profit": profit,
                "margin_pct": round((profit / revenue * 100) if revenue > 0 else 0, 1),
            })

        return projections

    # ------------------------------------------------------------------
    # LLM plan generation
    # ------------------------------------------------------------------

    def _generate_llm_plan(
        self,
        niche: str,
        research: dict,
        pricing: dict,
        projections: list[dict],
        budget: float,
    ) -> dict:
        """Ask the LLM to produce SWOT, risks, and recommendations."""
        total_12mo_profit = sum(p["profit"] for p in projections)

        prompt = (
            "You are a business strategy consultant for e-commerce.\n\n"
            f"Niche: {niche}\n"
            f"Investment Budget: ${budget:,.2f} AUD\n"
            f"Niche Score: {research.get('niche_score', 'N/A')}/100\n"
            f"Estimated Margin: {research.get('margin_estimate', 'N/A')}\n"
            f"Competitors Found: {research.get('competitor_count', 0)}\n"
            f"Suggested Price: ${pricing.get('pricing_tiers', {}).get('competitive', 'N/A')}\n"
            f"12-Month Projected Profit: ${total_12mo_profit:,.2f}\n\n"
            "Provide a JSON object with these keys:\n"
            "- swot: {strengths: [...], weaknesses: [...], opportunities: [...], threats: [...]}\n"
            "- risks: [{risk: str, likelihood: 'low'|'medium'|'high', impact: 'low'|'medium'|'high', mitigation: str}]\n"
            "- recommendations: [str] (5-7 actionable recommendations)"
        )

        try:
            result = self.llm.query(prompt, mode="claude", max_tokens=1500)
            text = result.get("text", "").strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
            return json.loads(text)
        except Exception as exc:
            logger.warning("LLM plan generation failed: %s", exc)
            return {
                "swot": {
                    "strengths": ["Low operational cost via automation"],
                    "weaknesses": ["New market entry"],
                    "opportunities": ["Growing e-commerce demand"],
                    "threats": ["Established competitors"],
                },
                "risks": [
                    {"risk": "Slow initial sales", "likelihood": "medium", "impact": "medium", "mitigation": "Start with small inventory."},
                ],
                "recommendations": [
                    "Start with the competitive pricing tier",
                    "Focus on a single marketplace initially (eBay)",
                    "Reinvest early profits into inventory",
                ],
            }
