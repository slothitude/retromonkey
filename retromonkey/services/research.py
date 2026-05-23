"""Market research service — niche analysis, trends, competitor data."""

import logging
from datetime import datetime, timezone

from retromonkey.app import db
from retromonkey.models.product import Product
from retromonkey.models.supplier import Supplier
from retromonkey.services.llm_router import LLMRouter

logger = logging.getLogger(__name__)


class ResearchService:
    """Full niche research pipeline: trends -> competitors -> scoring -> recommendation."""

    def __init__(self, db_instance, llm_router=None):
        self.db = db_instance or db
        self.llm = llm_router or LLMRouter()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def research_niche(self, niche: str, depth: str = "standard") -> dict:
        """Run the full research pipeline for a niche keyword.

        Parameters
        ----------
        niche : str
            The niche / product keyword to research.
        depth : str
            ``quick`` (trends only), ``standard`` (trends + competitors),
            ``deep`` (standard + LLM recommendation).

        Returns
        -------
        dict
            Keys: niche, trends, competitors, niche_score, seasonality,
            recommendation (when deep), margin_estimate.
        """
        trends = self._get_google_trends(niche)
        competitors = []

        if depth in ("standard", "deep"):
            competitors = self._get_competitor_data(niche)

        bsr = self._estimate_bsr(competitors)
        niche_score = self._calculate_niche_score(trends, competitors, bsr)
        margin = self._estimate_margin(competitors)
        seasonality = self._analyze_seasonality(trends)

        result = {
            "niche": niche,
            "depth": depth,
            "trends": trends,
            "competitors": competitors,
            "competitor_count": len(competitors),
            "niche_score": round(niche_score, 2),
            "margin_estimate": round(margin, 2),
            "seasonality": seasonality,
            "researched_at": datetime.now(timezone.utc).isoformat(),
        }

        if depth == "deep":
            result["recommendation"] = self._generate_recommendation(
                niche_score, trends, competitors
            )

        return result

    # ------------------------------------------------------------------
    # Google Trends
    # ------------------------------------------------------------------

    def _get_google_trends(self, keyword: str) -> list[dict]:
        """Fetch Google Trends interest over time via pytrends.

        Returns a list of dicts with ``date`` and ``interest`` keys.
        Falls back to an empty list when pytrends is unavailable or the
        request fails.
        """
        try:
            from pytrends.request import TrendReq

            pytrends = TrendReq(hl="en-AU", tz=360)
            pytrends.build_payload([keyword], cat=0, timeframe="today 12-m")
            df = pytrends.interest_over_time()

            if df.empty:
                return []

            trends = []
            for date, row in df.iterrows():
                trends.append({
                    "date": date.strftime("%Y-%m-%d"),
                    "interest": int(row[keyword]),
                })
            return trends

        except ImportError:
            logger.warning("pytrends not installed — returning empty trends")
            return []
        except Exception as exc:
            logger.warning("Google Trends fetch failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Competitor data
    # ------------------------------------------------------------------

    def _get_competitor_data(self, keyword: str) -> list[dict]:
        """Search eBay for competitor listings matching *keyword*.

        Returns a list of dicts with title, price, seller, condition.
        """
        from retromonkey.models.marketplace import Marketplace
        from retromonkey.connectors.ebay import EbayConnector
        from flask import current_app

        try:
            mp = self.db.session.query(Marketplace).filter_by(name="eBay", active=True).first()
            if not mp:
                return []
            connector = EbayConnector(mp, current_app.config)
            if not connector.is_authenticated():
                return []
            results = connector.search(keyword)
            return results[:20]
        except Exception as exc:
            logger.warning("Competitor data fetch failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Scoring helpers
    # ------------------------------------------------------------------

    def _calculate_niche_score(
        self,
        trends: list[dict],
        competitors: list[dict],
        bsr: float | None = None,
    ) -> float:
        """Weighted niche score.

        Formula: demand * 0.4 + margin * 0.35 + competition_inv * 0.25

        All sub-scores are normalised to 0-100.
        """
        # Demand score (from trends)
        if trends:
            avg_interest = sum(t["interest"] for t in trends) / len(trends)
            demand_score = min(avg_interest, 100)
        else:
            demand_score = 50  # neutral default

        # Margin score
        margin = self._estimate_margin(competitors)
        margin_score = margin * 100  # already 0-1 ratio

        # Competition inverse score
        if competitors:
            competition_score = max(0, 100 - len(competitors) * 2)
        else:
            competition_score = 50  # unknown

        # Optional BSR boost (lower BSR = better)
        if bsr is not None:
            bsr_boost = max(0, 100 - bsr / 10)
            demand_score = (demand_score + bsr_boost) / 2

        return demand_score * 0.4 + margin_score * 0.35 + competition_score * 0.25

    def _estimate_margin(self, competitors: list[dict]) -> float:
        """Estimate gross margin ratio from competitor prices.

        Assumes typical sourcing cost is ~30% of retail price.
        Returns a float in range 0-1.
        """
        if not competitors:
            return 0.50  # default 50% margin assumption

        prices = [c.get("price", 0) for c in competitors if c.get("price", 0) > 0]
        if not prices:
            return 0.50

        avg_price = sum(prices) / len(prices)
        if avg_price == 0:
            return 0.50

        estimated_cost = avg_price * 0.30
        return max(0, min(1, (avg_price - estimated_cost) / avg_price))

    def _estimate_bsr(self, competitors: list[dict]) -> float | None:
        """Estimate Amazon BSR from competitor data (placeholder).

        Returns None when no BSR data is available.
        """
        # In production this would query Amazon BSR via SP-API
        return None

    # ------------------------------------------------------------------
    # Seasonality
    # ------------------------------------------------------------------

    def _analyze_seasonality(self, trends: list[dict]) -> dict:
        """Group trend data by month and identify peak/trough months."""
        if not trends:
            return {"pattern": "unknown", "monthly": {}}

        monthly: dict[str, list[int]] = {}
        for t in trends:
            month = t["date"][:7]  # YYYY-MM
            monthly.setdefault(month, []).append(t["interest"])

        monthly_avg = {m: sum(v) / len(v) for m, v in monthly.items()}

        if not monthly_avg:
            return {"pattern": "unknown", "monthly": {}}

        peak_month = max(monthly_avg, key=monthly_avg.get)
        trough_month = min(monthly_avg, key=monthly_avg.get)

        values = list(monthly_avg.values())
        variance = max(values) - min(values)
        pattern = "seasonal" if variance > 30 else "stable"

        return {
            "pattern": pattern,
            "peak_month": peak_month,
            "trough_month": trough_month,
            "variance": round(variance, 2),
            "monthly": {m: round(v, 2) for m, v in monthly_avg.items()},
        }

    # ------------------------------------------------------------------
    # LLM recommendation
    # ------------------------------------------------------------------

    def _generate_recommendation(
        self,
        score: float,
        trends: list[dict],
        competitors: list[dict],
    ) -> dict:
        """Ask the LLM for a go/no-go recommendation with reasoning."""
        avg_interest = (
            round(sum(t["interest"] for t in trends) / len(trends), 1)
            if trends
            else "N/A"
        )
        price_range = ""
        prices = [c.get("price", 0) for c in competitors if c.get("price", 0) > 0]
        if prices:
            price_range = f"${min(prices):.2f} - ${max(prices):.2f}"

        prompt = (
            f"You are an e-commerce market analyst.\n"
            f"Niche Score: {score:.1f}/100\n"
            f"Average Google Trends Interest: {avg_interest}\n"
            f"Number of Competitors: {len(competitors)}\n"
            f"Competitor Price Range: {price_range or 'N/A'}\n\n"
            f"Provide a JSON response with these keys:\n"
            f"- verdict: 'enter' | 'caution' | 'avoid'\n"
            f"- reasoning: 2-3 sentence explanation\n"
            f"- suggested_price_range: [low, high] in AUD\n"
            f"- risk_level: 'low' | 'medium' | 'high'\n"
            f"- opportunity_score: 1-10"
        )

        try:
            result = self.llm.query(prompt, mode="auto", max_tokens=512)
            import json

            text = result.get("text", "").strip()
            # Strip markdown code fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
            return json.loads(text)
        except Exception as exc:
            logger.warning("LLM recommendation failed: %s", exc)
            if score >= 70:
                return {"verdict": "enter", "reasoning": f"High niche score ({score:.1f}).", "risk_level": "low"}
            elif score >= 45:
                return {"verdict": "caution", "reasoning": f"Moderate niche score ({score:.1f}).", "risk_level": "medium"}
            else:
                return {"verdict": "avoid", "reasoning": f"Low niche score ({score:.1f}).", "risk_level": "high"}
