"""AliExpress API connector — product search, order creation, tracking.

Uses the AliExpress Dropshipping API (AppKey: 535696).
Env vars: ALIEXPRESS_APP_KEY, ALIEXPRESS_APP_SECRET, ALIEXPRESS_ACCESS_TOKEN
Tokens are persisted to instance/aliexpress_tokens.json (auto-loads on init).
"""

import hashlib
import hmac
import json
import logging
import os
import time
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

API_BASE = "https://api-sg.aliexpress.com/openapi"
AUTH_BASE = "https://auth-sg.aliexpress.com/oauth/authorize"

# Token file path (Flask instance folder — same volume as DB)
TOKENS_PATH = os.path.join(
    os.environ.get('FLASK_INSTANCE_PATH', os.path.join(os.path.dirname(__file__), '..', 'instance')),
    'aliexpress_tokens.json'
)


class AliExpressConnector:
    """Wrapper for the AliExpress Dropshipping API."""

    def __init__(self):
        self.app_key = os.environ.get('ALIEXPRESS_APP_KEY', '')
        self.app_secret = os.environ.get('ALIEXPRESS_APP_SECRET', '')
        self.access_token = os.environ.get('ALIEXPRESS_ACCESS_TOKEN', '')
        self.refresh_token = ''
        self.token_expires_at = 0
        # Auto-load persisted tokens if no env var override
        if not self.access_token:
            self._load_tokens()

    @property
    def is_configured(self) -> bool:
        return bool(self.app_key and self.app_secret)

    @property
    def has_valid_token(self) -> bool:
        """True if we have an unexpired access token."""
        return bool(self.access_token and time.time() < self.token_expires_at)

    # ── Token persistence ──

    def _load_tokens(self):
        """Load tokens from JSON file."""
        try:
            if os.path.exists(TOKENS_PATH):
                with open(TOKENS_PATH) as f:
                    data = json.load(f)
                self.access_token = data.get('access_token', '')
                self.refresh_token = data.get('refresh_token', '')
                self.token_expires_at = data.get('token_expires_at', 0)
                if self.access_token:
                    logger.info("AliExpress tokens loaded from %s (expires %s)",
                                TOKENS_PATH, time.ctime(self.token_expires_at))
        except Exception as exc:
            logger.warning("Failed to load AliExpress tokens: %s", exc)

    def _save_tokens(self):
        """Persist tokens to JSON file."""
        try:
            os.makedirs(os.path.dirname(TOKENS_PATH), exist_ok=True)
            with open(TOKENS_PATH, 'w') as f:
                json.dump({
                    'access_token': self.access_token,
                    'refresh_token': self.refresh_token,
                    'token_expires_at': self.token_expires_at,
                }, f, indent=2)
            logger.info("AliExpress tokens saved to %s", TOKENS_PATH)
        except Exception as exc:
            logger.error("Failed to save AliExpress tokens: %s", exc)

    # ── OAuth ──

    def get_auth_url(self, redirect_uri: str, state: str = '') -> str:
        """Generate AliExpress OAuth authorization URL."""
        params = {
            'client_id': self.app_key,
            'redirect_uri': redirect_uri,
            'response_type': 'code',
        }
        if state:
            params['state'] = state
        return f"{AUTH_BASE}?{urlencode(params)}"

    def exchange_code_for_token(self, code: str, redirect_uri: str) -> dict:
        """Exchange authorization code for access/refresh tokens.

        Returns token info dict and saves to disk.
        """
        result = self._call('aliexpress.oauth.token.get', {
            'code': code,
            'redirect_uri': redirect_uri,
        })

        # Token response format: aliexpress_oauth_token_get_response -> {access_token, refresh_token, ...}
        token_data = result
        self.access_token = token_data.get('access_token', '')
        self.refresh_token = token_data.get('refresh_token', '')
        expires_in = int(token_data.get('expires_in', 28800))  # Default 8h
        self.token_expires_at = int(time.time()) + expires_in - 300  # 5 min buffer

        self._save_tokens()

        return {
            'access_token': self.access_token[:20] + '...',
            'refresh_token': self.refresh_token[:20] + '...' if self.refresh_token else '',
            'expires_in': expires_in,
            'user_nick': token_data.get('user_nick', ''),
            'saved': True,
        }

    def refresh_access_token(self) -> bool:
        """Refresh the access token using the refresh token. Returns True on success."""
        if not self.refresh_token:
            logger.warning("Cannot refresh AliExpress token: no refresh_token")
            return False

        try:
            result = self._call('aliexpress.oauth.token.refresh', {
                'refresh_token': self.refresh_token,
            })

            token_data = result
            self.access_token = token_data.get('access_token', '')
            new_refresh = token_data.get('refresh_token', '')
            if new_refresh:
                self.refresh_token = new_refresh
            expires_in = int(token_data.get('expires_in', 28800))
            self.token_expires_at = int(time.time()) + expires_in - 300

            self._save_tokens()
            logger.info("AliExpress token refreshed (expires in %ds)", expires_in)
            return True
        except Exception as exc:
            logger.error("AliExpress token refresh failed: %s", exc)
            return False

    def _sign(self, params: dict) -> str:
        """Generate API signature per AliExpress spec."""
        sorted_params = sorted(params.items())
        query_string = ''.join(f'{k}{v}' for k, v in sorted_params)
        sign_str = self.app_secret + query_string + self.app_secret
        return hmac.new(
            self.app_secret.encode(), sign_str.encode(), hashlib.sha256
        ).hexdigest().upper()

    def _common_params(self) -> dict:
        return {
            'app_key': self.app_key,
            'timestamp': str(int(time.time() * 1000)),
            'sign_method': 'sha256',
            'v': '2.0',
            'format': 'json',
        }

    def _call(self, method: str, params: dict = None, require_token: bool = False) -> dict:
        """Make an API call and return parsed JSON.

        If require_token=True and the token is expired, attempts a refresh first.
        """
        if not self.is_configured:
            raise RuntimeError("AliExpress API not configured (missing ALIEXPRESS_APP_KEY or ALIEXPRESS_APP_SECRET)")

        # Auto-refresh expired token for authenticated calls
        if require_token and self.refresh_token and not self.has_valid_token:
            self.refresh_access_token()

        all_params = self._common_params()
        all_params['method'] = method
        if params:
            all_params.update(params)
        if self.access_token:
            all_params['session'] = self.access_token
        all_params['sign'] = self._sign(all_params)

        resp = httpx.post(
            API_BASE,
            data=urlencode(all_params),
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        # AliExpress wraps responses: aliexpress_open_api_xxx_response
        response_key = method.replace('.', '_') + '_response'
        if response_key in data:
            return data[response_key]
        if 'error_response' in data:
            error = data['error_response']
            raise RuntimeError(f"AliExpress API error: {error.get('msg', data)}")
        return data

    def search_products(self, keywords: str, page_size: int = 20) -> list[dict]:
        """Search for products on AliExpress."""
        result = self._call('aliexpress.dropship.product.search', {
            'keywords': keywords,
            'page_size': page_size,
            'sort': 'SALE_PRICE_ASC',
        })
        products = result.get('product_list', result.get('products', []))
        return [
            {
                'id': p.get('product_id'),
                'title': p.get('subject', p.get('title', '')),
                'price': float(p.get('sale_price') or p.get('target_sale_price') or p.get('price', 0)),
                'original_price': float(p.get('original_price', 0)),
                'image_url': p.get('image_url', p.get('main_image_url', '')),
                'product_url': p.get('product_detail_url', p.get('product_url', '')),
                'shop_url': p.get('shop_url', ''),
                'shop_name': p.get('shop_name', ''),
                'rating': float(p.get('feedback_rating', 0)),
                'orders': int(p.get('lastest_ship_quantity', p.get('sale_count', 0))),
            }
            for p in products
        ]

    def get_product_details(self, product_id: str) -> dict:
        """Get detailed product info."""
        return self._call('aliexpress.dropship.product.get', {
            'product_ids': product_id,
            'fields': 'product_id,subject,sale_price,original_price,image_url,product_detail_url,'
                     'target_sale_price,shop_url,shop_name,feedback_rating,lastest_ship_quantity,'
                     'description,specs,shipping_info',
        })

    def create_order(self, product_id: str, address: dict, quantity: int = 1) -> dict:
        """Place a dropship order on AliExpress."""
        if not self.access_token:
            raise RuntimeError("AliExpress access token required for order creation")
        result = self._call('aliexpress.dropship.order.create', {
            'product_id': product_id,
            'quantity': quantity,
            'shipping_first_name': address.get('first_name', ''),
            'shipping_last_name': address.get('last_name', ''),
            'shipping_phone': address.get('phone', ''),
            'shipping_address_line_1': address.get('address_line_1', ''),
            'shipping_city': address.get('city', ''),
            'shipping_state': address.get('state', ''),
            'shipping_zip': address.get('zip', ''),
            'shipping_country': address.get('country', 'AU'),
        })
        return {
            'order_id': result.get('order_id', result.get('aliexpress_order_id')),
            'status': result.get('status', 'created'),
            'payment_url': result.get('payment_url', ''),
        }

    def get_order_tracking(self, order_id: str) -> dict:
        """Get tracking info for an AliExpress dropship order."""
        return self._call('aliexpress.dropship.logistics.get', {
            'order_id': order_id,
        }, require_token=True)

    def get_order_detail(self, order_id: str) -> dict:
        """Get full order detail."""
        return self._call('aliexpress.dropship.order.get', {
            'order_id': order_id,
        }, require_token=True)
