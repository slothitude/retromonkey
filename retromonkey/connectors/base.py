from abc import ABC, abstractmethod
import logging
import time


class BaseConnector(ABC):
    """Abstract base for all marketplace connectors."""

    MARKETPLACE_NAME: str = ''

    def __init__(self, marketplace_record, config):
        self.marketplace = marketplace_record
        self.config = config
        self.logger = logging.getLogger(f'connector.{self.MARKETPLACE_NAME}')
        self._rate_limits = {}

    @abstractmethod
    def authenticate(self) -> dict:
        """Obtain/refresh auth tokens."""

    @abstractmethod
    def is_authenticated(self) -> bool:
        """Check if current tokens are valid."""

    @abstractmethod
    def list_item(self, product, listing_data: dict) -> dict:
        """Create a listing. Returns {external_id, status, url}."""

    @abstractmethod
    def update_listing(self, listing, update_data: dict) -> dict:
        """Update listing. Returns {status}."""

    @abstractmethod
    def end_listing(self, listing) -> dict:
        """End/remove a listing."""

    @abstractmethod
    def get_orders(self, filters: dict = None) -> list[dict]:
        """Pull orders from marketplace."""

    @abstractmethod
    def get_order(self, external_order_id: str) -> dict:
        """Get single order details."""

    @abstractmethod
    def ship_order(self, external_order_id: str, carrier: str, tracking_number: str) -> dict:
        """Mark order as shipped."""

    @abstractmethod
    def get_inventory(self) -> list[dict]:
        """Pull inventory from marketplace."""

    @abstractmethod
    def search(self, query: str, filters: dict = None) -> list[dict]:
        """Search marketplace for products."""

    def _rate_limit(self, endpoint: str, min_interval: float = 1.0):
        last = self._rate_limits.get(endpoint, 0)
        wait = min_interval - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
        self._rate_limits[endpoint] = time.time()

    def _retry(self, fn, max_retries=3, backoff=2):
        for attempt in range(max_retries):
            try:
                return fn()
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                self.logger.warning(f"Retry {attempt+1}/{max_retries}: {e}")
                time.sleep(backoff ** attempt)
