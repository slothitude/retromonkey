"""AI listing optimization — titles, descriptions, keywords, category suggestions."""

import json
import logging
from datetime import datetime, timezone

from retromonkey.app import db
from retromonkey.models.product import Product
from retromonkey.models.marketplace import Listing
from retromonkey.services.llm_router import LLMRouter

logger = logging.getLogger(__name__)

# eBay title length limits
TITLE_LENGTH_LIMITS = {
    "ebay": 80,
    "amazon": 200,
    "kogan": 120,
    "default": 120,
}


class ListingAIService:
    """Generate optimized listing content using LLM."""

    def __init__(self, db_instance, llm_router=None):
        self.db = db_instance or db
        self.llm = llm_router or LLMRouter()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def optimize_listing(
        self,
        product_id: int,
        marketplace: str = "ebay",
    ) -> dict:
        """Generate a fully optimized listing for a product.

        Parameters
        ----------
        product_id : int
            Product to optimize.
        marketplace : str
            Target marketplace name (affects title length etc).

        Returns
        -------
        dict
            Keys: title, description, keywords, category_suggestions.
        """
        product = self.db.session.get(Product, product_id)
        if not product:
            raise ValueError(f"Product {product_id} not found")

        title = self._generate_title(product, marketplace)
        description = self._generate_description(product)
        keywords = self._extract_keywords(title, description)
        category_suggestions = self._suggest_category(title)

        return {
            "product_id": product_id,
            "sku": product.sku,
            "marketplace": marketplace,
            "title": title,
            "description": description,
            "keywords": keywords,
            "category_suggestions": category_suggestions,
            "optimized_at": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # Title generation
    # ------------------------------------------------------------------

    def _generate_title(self, product: Product, marketplace: str) -> str:
        """Generate an SEO-optimized title respecting marketplace length limits."""
        limit = TITLE_LENGTH_LIMITS.get(marketplace.lower(), TITLE_LENGTH_LIMITS["default"])

        prompt = (
            "You are an e-commerce SEO specialist. Generate an optimized product title "
            "for an eBay listing.\n\n"
            f"Product: {product.title}\n"
            f"Category: {product.category or 'General'}\n"
            f"Condition: {product.condition or 'New'}\n"
            f"Description: {(product.description or '')[:300]}\n\n"
            f"Rules:\n"
            f"- Maximum {limit} characters\n"
            f"- Include brand, key features, size/colour if relevant\n"
            f"- Use high-search-volume keywords\n"
            f"- Do NOT use all caps or excessive punctuation\n"
            f"- Output ONLY the title text, nothing else"
        )

        result = self.llm.query(prompt, mode="auto", max_tokens=128)
        title = result.get("text", "").strip()

        # Truncate if over limit
        if len(title) > limit:
            title = title[:limit].rsplit(" ", 1)[0]

        # Fallback to original title if generation failed
        if not title:
            title = product.title[:limit]

        return title

    # ------------------------------------------------------------------
    # Description generation
    # ------------------------------------------------------------------

    def _generate_description(self, product: Product) -> str:
        """Generate an HTML-formatted product description."""
        prompt = (
            "You are an e-commerce copywriter. Create a compelling product description "
            "formatted in clean HTML.\n\n"
            f"Product: {product.title}\n"
            f"Category: {product.category or 'General'}\n"
            f"Condition: {product.condition or 'New'}\n"
            f"Existing Description: {product.description or 'N/A'}\n\n"
            "Format:\n"
            "<h3>Product Description</h3>\n"
            "<p>Main description paragraph</p>\n"
            "<h3>Key Features</h3>\n"
            "<ul><li>Feature 1</li><li>Feature 2</li>...</ul>\n"
            "<h3>Specifications</h3>\n"
            "<table><tr><td>Spec</td><td>Value</td></tr>...</table>\n"
            "<p><em>Shipping and return information</em></p>\n\n"
            "Output ONLY the HTML, nothing else."
        )

        result = self.llm.query(prompt, mode="auto", max_tokens=1024)
        description = result.get("text", "").strip()

        if not description:
            # Fallback description
            description = (
                f"<h3>{product.title}</h3>\n"
                f"<p>{product.description or 'Quality product at a great price.'}</p>\n"
            )

        return description

    # ------------------------------------------------------------------
    # Keywords
    # ------------------------------------------------------------------

    def _extract_keywords(self, title: str, description: str) -> str:
        """Extract comma-separated SEO keywords from title and description.

        Uses LLM for intelligent extraction, falls back to simple splitting.
        """
        prompt = (
            "Extract 15-20 SEO keywords and search terms from this product listing. "
            "Return ONLY a comma-separated list of keywords, no numbering or extra text.\n\n"
            f"Title: {title}\n"
            f"Description: {description[:500]}"
        )

        result = self.llm.query(prompt, mode="ollama", max_tokens=256)
        keywords = result.get("text", "").strip()

        if not keywords:
            # Fallback: split title into words
            words = title.lower().split()
            keywords = ", ".join(w for w in words if len(w) > 3)[:300]

        return keywords

    # ------------------------------------------------------------------
    # Category suggestions
    # ------------------------------------------------------------------

    def _suggest_category(self, title: str) -> list[dict]:
        """Suggest eBay categories via the Taxonomy API."""
        try:
            from retromonkey.models.marketplace import Marketplace
            from retromonkey.connectors.ebay import EbayConnector
            from flask import current_app

            mp = self.db.session.query(Marketplace).filter_by(name="eBay", active=True).first()
            if not mp:
                return []

            connector = EbayConnector(mp, current_app.config)
            suggestions = connector.get_category_suggestions(title)

            return [
                {
                    "category_id": s.get("categoryTreeId"),
                    "category_name": s.get("categoryTreeNodeLevel", ""),
                    "leaf_category": s.get("leafCategoryTreeNode", False),
                }
                for s in suggestions[:5]
            ]
        except Exception as exc:
            logger.warning("Category suggestion failed: %s", exc)
            return []
