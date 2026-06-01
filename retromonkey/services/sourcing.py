"""Alibaba sourcing service — search, scrape, store suppliers."""

import logging
import re
from datetime import datetime, timezone

import requests as http_requests
from bs4 import BeautifulSoup

from retromonkey.app import db
from retromonkey.models.supplier import Supplier

logger = logging.getLogger(__name__)


class SourcingService:
    """Search Alibaba for suppliers and persist results."""

    ALIBABA_SEARCH_URL = "https://www.alibaba.com/trade/search"

    def __init__(self, db_instance):
        self.db = db_instance or db

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def search_suppliers(
        self,
        keyword: str,
        filters: dict | None = None,
    ) -> list[dict]:
        """Search Alibaba for suppliers matching *keyword*.

        .. warning::
            Alibaba uses JS-rendered pages. The BeautifulSoup scraper
            typically returns empty results. Use the ``sourcing_add_manual``
            MCP tool for manual entry, or the AliExpress API connector.

        Parameters
        ----------
        keyword : str
            Product / supplier search term.
        filters : dict, optional
            Supported keys: ``min_price``, ``max_price``, ``min_moq``,
            ``max_moq``, ``trade_assurance`` (bool).

        Returns
        -------
        list[dict]
            Parsed supplier data dicts.
        """
        logger.warning(
            "Alibaba automated scraping is broken (JS-rendered pages). "
            "Results will likely be empty. Use sourcing_add_manual MCP tool instead."
        )
        filters = filters or {}
        raw_results = self._scrape_alibaba_search(keyword, filters)

        saved = []
        for entry in raw_results:
            supplier = self._upsert_supplier(entry)
            saved.append(self._supplier_to_dict(supplier))

        return saved

    # ------------------------------------------------------------------
    # Scraping
    # ------------------------------------------------------------------

    def _scrape_alibaba_search(
        self,
        keyword: str,
        filters: dict,
    ) -> list[dict]:
        """Scrape Alibaba search results page using BeautifulSoup."""
        params = {"SearchText": keyword, "viewtype": "G"}
        if filters.get("min_price"):
            params["priceBegin"] = filters["min_price"]
        if filters.get("max_price"):
            params["priceEnd"] = filters["max_price"]

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }

        try:
            resp = http_requests.get(
                self.ALIBABA_SEARCH_URL,
                params=params,
                headers=headers,
                timeout=30,
            )
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("Alibaba search request failed: %s", exc)
            return []

        return self._parse_search_page(resp.text, filters)

    def _parse_search_page(
        self, html: str, filters: dict
    ) -> list[dict]:
        """Extract supplier / product entries from HTML."""
        soup = BeautifulSoup(html, "html.parser")
        results = []

        # Alibaba renders product cards in various containers.
        # We target the most common selectors.
        cards = soup.select(".fy23-search-card, .organic-list div[data-content]")
        if not cards:
            # Fallback: generic product listing containers
            cards = soup.select(".J-II-list .list-item")

        for card in cards:
            entry = self._parse_card(card)
            if not entry:
                continue

            # Apply MOQ filters
            if filters.get("min_moq") and entry.get("moq", 0) < filters["min_moq"]:
                continue
            if filters.get("max_moq") and entry.get("moq", 0) > filters["max_moq"]:
                continue
            if filters.get("trade_assurance") and not entry.get("trade_assurance"):
                continue

            results.append(entry)

        return results

    def _parse_card(self, card) -> dict | None:
        """Parse a single result card element."""
        try:
            # Name
            title_el = card.select_one(".title, .elements-title-normal, a.title")
            name = title_el.get_text(strip=True) if title_el else None
            if not name:
                return None

            # URL
            link_el = card.select_one("a[href*='alibaba.com']")
            url = link_el["href"] if link_el and link_el.get("href") else ""

            # Price
            price_el = card.select_one(".price, .elements-price-normal")
            price_text = price_el.get_text(strip=True) if price_el else ""
            price = self._parse_price(price_text)

            # MOQ
            moq_el = card.select_one(".moq, .min-order")
            moq_text = moq_el.get_text(strip=True) if moq_el else ""
            moq = self._parse_moq(moq_text)

            # Rating
            rating_el = card.select_one(".rating, .star-level")
            rating = self._parse_rating(rating_el)

            # Trade assurance badge
            ta_el = card.select_one(".trade-assurance, .ta-icon")
            trade_assurance = ta_el is not None

            return {
                "name": name[:128],
                "url": url[:512],
                "price": price,
                "moq": moq,
                "rating": rating,
                "trade_assurance": trade_assurance,
            }
        except Exception as exc:
            logger.debug("Card parse error: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_moq(text: str) -> int | None:
        """Extract MOQ number from text like 'Min. Order: 50 Pieces'."""
        if not text:
            return None
        # Match patterns: "50 Pieces", "10 pcs", "Min. Order: 100"
        match = re.search(r"(\d[\d,]*)\s*(?:pieces?|pcs?|units?|items?|pairs?|sets?)?", text, re.I)
        if match:
            return int(match.group(1).replace(",", ""))
        return None

    @staticmethod
    def _parse_price(text: str) -> float | None:
        """Extract a price from text like '$12.50 - $15.00'."""
        if not text:
            return None
        match = re.search(r"\$?([\d]+(?:\.\d{2})?)", text)
        return float(match.group(1)) if match else None

    @staticmethod
    def _parse_rating(element) -> float | None:
        """Parse star rating from element."""
        if element is None:
            return None
        text = element.get_text(strip=True)
        match = re.search(r"([\d.]+)", text)
        return float(match.group(1)) if match else None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _upsert_supplier(self, data: dict) -> Supplier:
        """Create or update a Supplier record from parsed data."""
        existing = None
        if data.get("url"):
            existing = self.db.session.query(Supplier).filter_by(
                url=data["url"]
            ).first()

        if existing:
            if data.get("rating") is not None:
                existing.rating = data["rating"]
            if data.get("trade_assurance") is not None:
                existing.trade_assurance = data["trade_assurance"]
            if data.get("moq") is not None:
                existing.min_order_qty = data["moq"]
            self.db.session.commit()
            return existing

        supplier = Supplier(
            name=data.get("name", "Unknown"),
            platform="Alibaba",
            url=data.get("url"),
            rating=data.get("rating"),
            trade_assurance=data.get("trade_assurance", False),
            min_order_qty=data.get("moq"),
        )
        self.db.session.add(supplier)
        self.db.session.commit()
        return supplier

    @staticmethod
    def _supplier_to_dict(supplier: Supplier) -> dict:
        return {
            "id": supplier.id,
            "name": supplier.name,
            "platform": supplier.platform,
            "url": supplier.url,
            "rating": supplier.rating,
            "trade_assurance": supplier.trade_assurance,
            "min_order_qty": supplier.min_order_qty,
            "verified": supplier.verified,
        }
