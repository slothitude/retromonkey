"""AliExpress Dropshipping API connector — product search, order creation, tracking.

Uses the AliExpress IOP SDK (Java SDK) with TWO protocols:
  - GOP protocol: POST /rest/{apiName} — for auth/token endpoints
      - apiName has leading slash (e.g., /auth/token/create)
      - Sign string = apiName + sorted(key+value)
  - TOP protocol: POST /sync?method={apiName} — for business DS endpoints
      - apiName has NO leading slash (e.g., aliexpress.ds.order.tracking.get)
      - Sign string = sorted(key+value) (no apiName prefix)
      - Common params include: app_key, v, timestamp, method, format, session, sign, sign_method

Signing (both): HMAC-SHA256(key=app_secret, message=sign_string) → uppercase hex

AppKey: 535696
Env vars: ALIEXPRESS_APP_KEY, ALIEXPRESS_APP_SECRET, ALIEXPRESS_ACCESS_TOKEN
Tokens persisted to instance/aliexpress_tokens.json (auto-loads on init).
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

API_BASE = "https://api-sg.aliexpress.com"
AUTH_BASE = "https://api-sg.aliexpress.com/oauth/authorize"

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
            'force_auth': 'true',
        }
        if state:
            params['state'] = state
        return f"{AUTH_BASE}?{urlencode(params)}"

    # ── IOP SDK signing ──

    def _hmac_sign(self, sign_str: str) -> str:
        """HMAC-SHA256 sign and return uppercase hex."""
        return hmac.new(
            self.app_secret.encode(), sign_str.encode(), hashlib.sha256
        ).hexdigest().upper()

    def _sign_gop(self, api_name: str, params: dict) -> str:
        """GOP protocol signing: apiName + sorted(key+value)."""
        sorted_params = sorted(params.items())
        sign_str = api_name + ''.join(f'{k}{v}' for k, v in sorted_params)
        return self._hmac_sign(sign_str)

    def _sign_top(self, params: dict) -> str:
        """TOP protocol signing: just sorted(key+value), no apiName prefix."""
        sorted_params = sorted(params.items())
        sign_str = ''.join(f'{k}{v}' for k, v in sorted_params)
        return self._hmac_sign(sign_str)

    # ── GOP protocol call (auth/token endpoints) ──

    def _gop_call(self, api_name: str, biz_params: dict = None) -> dict:
        """POST /rest/{api_name} with GOP signing.

        Used for auth/token endpoints. api_name must have leading slash.
        Common params (app_key, timestamp, sign_method, sign, access_token) in URL query.
        Business params in POST body as form-encoded data.
        """
        if not self.is_configured:
            raise RuntimeError("AliExpress API not configured")

        if biz_params is None:
            biz_params = {}

        common = {
            'app_key': self.app_key,
            'timestamp': str(int(time.time() * 1000)),
            'sign_method': 'sha256',
        }
        if self.access_token:
            common['access_token'] = self.access_token

        all_params = {**common, **biz_params}
        common['sign'] = self._sign_gop(api_name, all_params)

        url = f"{API_BASE}/rest{api_name}?{urlencode(common)}"
        resp = httpx.post(
            url,
            data=urlencode(biz_params),
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    # ── TOP protocol call (business DS endpoints) ──

    def _top_call(self, api_name: str, biz_params: dict = None,
                  require_token: bool = False) -> dict:
        """POST /sync?method={api_name} with TOP signing.

        Used for business dropshipping endpoints. api_name has NO leading slash.
        Common params (app_key, v, timestamp, method, format, session, sign, sign_method)
        in URL query. Business params in POST body.
        """
        if not self.is_configured:
            raise RuntimeError("AliExpress API not configured")

        # Auto-refresh expired token for authenticated calls
        if require_token and self.refresh_token and not self.has_valid_token:
            self.refresh_access_token()

        if biz_params is None:
            biz_params = {}

        # TOP protocol common params (matches Java SDK TopExecutor)
        common = {
            'app_key': self.app_key,
            'v': '2.0',
            'timestamp': str(int(time.time() * 1000)),
            'method': api_name,
            'format': 'json',
            'sign_method': 'sha256',
        }
        if self.access_token:
            common['session'] = self.access_token

        # Sign: empty apiName + sorted(all_params)
        all_params = {**common, **biz_params}
        common['sign'] = self._sign_top(all_params)

        url = f"{API_BASE}/sync?{urlencode(common)}"
        resp = httpx.post(
            url,
            data=urlencode(biz_params),
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    # ── Response parsing ──

    def _parse_response(self, data: dict, api_name: str = '') -> dict:
        """Parse GOP/TOP response, unwrapping protocol-specific wrappers.

        GOP: wraps body in gopResponseBody as JSON string.
        TOP: wraps in {api_name_underscores_response: {result: ...}}.
        """
        # Unwrap GOP response body
        if data.get('gopResponseBody'):
            try:
                data = json.loads(data['gopResponseBody'])
            except (json.JSONDecodeError, TypeError):
                pass

        # Check for ISV error (both protocols)
        if data.get('type') == 'ISV':
            logger.error("AliExpress ISV error full response: %s", json.dumps(data, default=str))
            raise RuntimeError(f"AliExpress API error [{data.get('code')}]: {data.get('message') or data.get('sub_msg', '')}")

        # Check GOP error code
        code = data.get('gopErrorCode', '0')
        if code and code != '0':
            raise RuntimeError(f"AliExpress API error [{code}]: {data}")

        # Unwrap TOP response: find {api_name_response: ...} key
        if api_name:
            response_key = api_name.replace('.', '_') + '_response'
            if response_key in data:
                inner = data[response_key]
                # Check for TOP error inside wrapper
                rsp_code = inner.get('rsp_code', inner.get('code', ''))
                rsp_msg = inner.get('rsp_msg', inner.get('msg', ''))
                if rsp_code and rsp_code != 200 and rsp_code != '200' and rsp_code != '0':
                    raise RuntimeError(f"AliExpress API error [{rsp_code}]: {rsp_msg}")
                if inner.get('error_response'):
                    error = inner['error_response']
                    raise RuntimeError(f"AliExpress API error: {error.get('msg', error)}")
                return inner

        # Check for TOP-style error at top level
        if 'error_response' in data:
            error = data['error_response']
            raise RuntimeError(f"AliExpress API error: {error.get('msg', data)}")

        return data

    # ── Token exchange (GOP protocol) ──

    def exchange_code_for_token(self, code: str, redirect_uri: str) -> dict:
        """Exchange authorization code for access/refresh tokens.

        Uses GOP protocol: POST /rest/auth/token/create
        """
        data = self._gop_call('/auth/token/create', {'code': code})
        token_data = self._parse_response(data)

        self.access_token = token_data.get('access_token', '')
        self.refresh_token = token_data.get('refresh_token', '')
        expires_in = int(token_data.get('expires_in', 86400))
        self.token_expires_at = int(time.time()) + expires_in - 300

        if not self.access_token:
            raise RuntimeError(f"AliExpress token exchange returned no access_token: {data}")

        self._save_tokens()

        return {
            'access_token': self.access_token[:20] + '...',
            'refresh_token': self.refresh_token[:20] + '...' if self.refresh_token else '',
            'expires_in': expires_in,
            'user_nick': token_data.get('user_nick', ''),
            'user_id': token_data.get('user_id', ''),
            'seller_id': token_data.get('seller_id', ''),
            'saved': True,
        }

    def refresh_access_token(self) -> bool:
        """Refresh the access token using the refresh token. Returns True on success."""
        if not self.refresh_token:
            logger.warning("Cannot refresh AliExpress token: no refresh_token")
            return False

        try:
            data = self._gop_call('/auth/token/refresh', {'refresh_token': self.refresh_token})
            token_data = self._parse_response(data)

            self.access_token = token_data.get('access_token', '')
            new_refresh = token_data.get('refresh_token', '')
            if new_refresh:
                self.refresh_token = new_refresh
            expires_in = int(token_data.get('expires_in', 86400))
            self.token_expires_at = int(time.time()) + expires_in - 300

            self._save_tokens()
            logger.info("AliExpress token refreshed (expires in %ds)", expires_in)
            return True
        except Exception as exc:
            logger.error("AliExpress token refresh failed: %s", exc)
            return False

    # ── Dropshipping Business APIs (TOP protocol) ──

    def search_products(self, keywords: str, page_size: int = 20,
                         target_currency: str = 'USD',
                         target_language: str = 'en',
                         ship_to_country: str = 'AU') -> list[dict]:
        """Search for products on AliExpress dropshipping catalog.

        API: aliexpress.ds.text.search
        """
        data = self._top_call('aliexpress.ds.text.search', {
            'keywords': keywords,
            'currency': target_currency,
            'target_currency': target_currency,
            'target_language': target_language,
            'language': target_language,
            'local': target_language,
            'ship_to_country': ship_to_country,
            'countryCode': ship_to_country,
            'page_size': page_size,
            'pageSize': page_size,
        }, require_token=True)
        data = self._parse_response(data, 'aliexpress.ds.text.search')

        products = data.get('result', {}).get('products', data.get('products', []))
        return [
            {
                'id': p.get('product_id'),
                'title': p.get('subject', p.get('title', p.get('product_title', ''))),
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

    def get_product_details(self, product_id: str,
                            ship_to_country: str = 'AU',
                            target_currency: str = 'USD',
                            target_language: str = 'en') -> dict:
        """Get detailed product info from dropshipping catalog.

        API: aliexpress.ds.product.get
        """
        data = self._top_call('aliexpress.ds.product.get', {
            'product_id': product_id,
            'ship_to_country': ship_to_country,
            'target_currency': target_currency,
            'target_language': target_language,
        }, require_token=True)
        return self._parse_response(data, 'aliexpress.ds.product.get')

    def get_product_wholesale(self, product_id: str,
                               ship_to_country: str = 'AU',
                               target_currency: str = 'USD') -> dict:
        """Get wholesale pricing for a product.

        API: aliexpress.ds.product.wholesale.get
        """
        data = self._top_call('aliexpress.ds.product.wholesale.get', {
            'product_id': product_id,
            'ship_to_country': ship_to_country,
            'target_currency': target_currency,
        }, require_token=True)
        return self._parse_response(data, 'aliexpress.ds.product.wholesale.get')

    def get_freight(self, product_id: str, country: str = 'AU',
                    quantity: int = 1) -> dict:
        """Get freight/delivery options for a product.

        API: aliexpress.ds.freight.query
        """
        data = self._top_call('aliexpress.ds.freight.query', {
            'product_id': product_id,
            'country': country,
            'quantity': quantity,
        }, require_token=True)
        return self._parse_response(data, 'aliexpress.ds.freight.query')

    def create_order(self, product_id: str, address: dict, quantity: int = 1,
                     sku_attr: str = '', logistics_service_name: str = '',
                     out_order_id: str = '') -> dict:
        """Place a dropship order on AliExpress.

        API: aliexpress.ds.order.create
        Address dict keys: full_name, contact_person, mobile_no, phone_country,
                          address, address2, city, province, zip, country, locale
        """
        if not self.access_token:
            raise RuntimeError("AliExpress access token required for order creation")

        full_name = address.get('full_name', f"{address.get('first_name', '')} {address.get('last_name', '')}".strip())
        contact_person = address.get('contact_person', full_name)
        mobile_no = address.get('mobile_no', address.get('phone', ''))
        phone_country = address.get('phone_country', '+61')

        biz_params = {
            'param_place_order_request4_open_api_d_t_o.product_items.product_id': str(product_id),
            'param_place_order_request4_open_api_d_t_o.product_items.product_count': str(quantity),
            'param_place_order_request4_open_api_d_t_o.logistics_address.full_name': full_name,
            'param_place_order_request4_open_api_d_t_o.logistics_address.contact_person': contact_person,
            'param_place_order_request4_open_api_d_t_o.logistics_address.mobile_no': mobile_no,
            'param_place_order_request4_open_api_d_t_o.logistics_address.phone_country': phone_country,
            'param_place_order_request4_open_api_d_t_o.logistics_address.address': address.get('address', address.get('address_line_1', '')),
            'param_place_order_request4_open_api_d_t_o.logistics_address.city': address.get('city', ''),
            'param_place_order_request4_open_api_d_t_o.logistics_address.province': address.get('province', address.get('state', '')),
            'param_place_order_request4_open_api_d_t_o.logistics_address.zip': address.get('zip', ''),
            'param_place_order_request4_open_api_d_t_o.logistics_address.country': address.get('country', 'AU'),
            'param_place_order_request4_open_api_d_t_o.logistics_address.locale': address.get('locale', 'en_US'),
        }
        if sku_attr:
            biz_params['param_place_order_request4_open_api_d_t_o.product_items.sku_attr'] = sku_attr
        if logistics_service_name:
            biz_params['param_place_order_request4_open_api_d_t_o.product_items.logistics_service_name'] = logistics_service_name
        if out_order_id:
            biz_params['param_place_order_request4_open_api_d_t_o.out_order_id'] = out_order_id

        data = self._top_call('aliexpress.ds.order.create', biz_params, require_token=True)
        result = self._parse_response(data, 'aliexpress.ds.order.create').get('result', data)
        return {
            'order_id': result.get('order_list', [''])[0] if isinstance(result.get('order_list'), list) else result.get('order_id', ''),
            'is_success': result.get('is_success', False),
            'error_code': result.get('error_code', ''),
            'error_msg': result.get('error_msg', ''),
        }

    def get_order_tracking(self, order_id: str, language: str = 'en_US') -> dict:
        """Get tracking info for an AliExpress dropship order.

        API: aliexpress.ds.order.tracking.get
        Input: ae_order_id (the AliExpress order ID)
        Output: result.data.tracking_detail_line_list with carrier_name, mail_no,
                detail_node_list, package_item_list, eta_time_stamps
        """
        data = self._top_call('aliexpress.ds.order.tracking.get', {
            'ae_order_id': str(order_id),
            'language': language,
        }, require_token=True)
        return self._parse_response(data, 'aliexpress.ds.order.tracking.get')

    def get_order_detail(self, order_id: str) -> dict:
        """Get full order detail for a dropship order.

        API: aliexpress.ds.trade.order.get
        Input: order_id
        Output: order_status, logistics_status, order_amount, child_order_list,
                logistics_info_list, store_info, gmt_create, order_paidtime_string
        """
        data = self._top_call('aliexpress.ds.trade.order.get', {
            'order_id': str(order_id),
        }, require_token=True)
        return self._parse_response(data, 'aliexpress.ds.trade.order.get')

    def get_categories(self) -> list[dict]:
        """Fetch AE category IDs and names.

        API: aliexpress.ds.category.get
        """
        data = self._top_call('aliexpress.ds.category.get', {}, require_token=True)
        return self._parse_response(data, 'aliexpress.ds.category.get')

    def image_search(self, image_url: str = '', image_data: str = '') -> dict:
        """Search products by image.

        API: aliexpress.ds.image.searchV2
        """
        params = {}
        if image_url:
            params['image_url'] = image_url
        if image_data:
            params['image_data'] = image_data
        data = self._top_call('aliexpress.ds.image.searchV2', params, require_token=True)
        return self._parse_response(data, 'aliexpress.ds.image.searchV2')
