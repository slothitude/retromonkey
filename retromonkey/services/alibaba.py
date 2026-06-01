"""Alibaba.com Open Platform (ICBU) connector — B2B wholesale sourcing.

Uses the same IOP SDK GOP protocol as AliExpress but targets the
Alibaba.com B2B wholesale platform for supplier/product search,
freight calculation, order tracking, and BuyNow ordering.

APIs (all GOP protocol, POST /rest{path}):
  Auth:
    /auth/token/create   — exchange code for access token
    /auth/token/refresh  — refresh access token
  Product:
    /eco/buyer/product/search           — search products
    /eco/buyer/product/check             — list products with filters
    /alibaba/icbu/product/get/v2         — product details by ID
    /icbu/product/category/get          — category tree
  Freight:
    /shipping/freight/calculate         — basic freight estimate
    /order/freight/calculate             — advanced freight calculation
  Orders:
    /buynow/order/create                 — create BuyNow order
    /alibaba/order/get                   — order details
    /alibaba/order/list                  — list orders
    /order/logistics/tracking/get        — shipment tracking

Signing: HMAC-SHA256(key=app_secret, message=apiName + sorted(key+value)) → uppercase hex
Common params: app_key, timestamp, sign_method, sign, access_token

Env vars: ALIBABA_APP_KEY, ALIBABA_APP_SECRET, ALIBABA_ACCESS_TOKEN
Tokens persisted to instance/alibaba_tokens.json.
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

API_BASE = "https://openapi.alibaba.com"
AUTH_BASE = "https://openapi.alibaba.com/oauth/authorize"

TOKENS_PATH = os.path.join(
    os.environ.get('FLASK_INSTANCE_PATH', os.path.join(os.path.dirname(__file__), '..', 'instance')),
    'alibaba_tokens.json'
)


class AlibabaConnector:
    """Wrapper for the Alibaba.com Open Platform API (ICBU)."""

    def __init__(self):
        self.app_key = os.environ.get('ALIBABA_APP_KEY', '')
        self.app_secret = os.environ.get('ALIBABA_APP_SECRET', '')
        self.access_token = os.environ.get('ALIBABA_ACCESS_TOKEN', '')
        self.refresh_token = ''
        self.token_expires_at = 0
        if not self.access_token:
            self._load_tokens()

    @property
    def is_configured(self) -> bool:
        return bool(self.app_key and self.app_secret)

    @property
    def has_valid_token(self) -> bool:
        return bool(self.access_token and time.time() < self.token_expires_at)

    # ── Token persistence ──

    def _load_tokens(self):
        try:
            if os.path.exists(TOKENS_PATH):
                with open(TOKENS_PATH) as f:
                    data = json.load(f)
                self.access_token = data.get('access_token', '')
                self.refresh_token = data.get('refresh_token', '')
                self.token_expires_at = data.get('token_expires_at', 0)
                if self.access_token:
                    logger.info("Alibaba tokens loaded from %s (expires %s)",
                                TOKENS_PATH, time.ctime(self.token_expires_at))
        except Exception as exc:
            logger.warning("Failed to load Alibaba tokens: %s", exc)

    def _save_tokens(self):
        try:
            os.makedirs(os.path.dirname(TOKENS_PATH), exist_ok=True)
            with open(TOKENS_PATH, 'w') as f:
                json.dump({
                    'access_token': self.access_token,
                    'refresh_token': self.refresh_token,
                    'token_expires_at': self.token_expires_at,
                }, f, indent=2)
            logger.info("Alibaba tokens saved to %s", TOKENS_PATH)
        except Exception as exc:
            logger.error("Failed to save Alibaba tokens: %s", exc)

    # ── OAuth ──

    def get_auth_url(self, redirect_uri: str, state: str = '') -> str:
        """Generate Alibaba OAuth authorization URL."""
        params = {
            'client_id': self.app_key,
            'redirect_uri': redirect_uri,
            'response_type': 'code',
        }
        if state:
            params['state'] = state
        return f"{AUTH_BASE}?{urlencode(params)}"

    # ── IOP SDK signing (GOP protocol — same as AliExpress) ──

    def _hmac_sign(self, sign_str: str) -> str:
        return hmac.new(
            self.app_secret.encode(), sign_str.encode(), hashlib.sha256
        ).hexdigest().upper()

    def _sign(self, api_name: str, params: dict) -> str:
        """GOP signing: apiName + sorted(key+value)."""
        sorted_params = sorted(params.items())
        sign_str = api_name + ''.join(f'{k}{v}' for k, v in sorted_params)
        return self._hmac_sign(sign_str)

    # ── API call ──

    def _call(self, api_path: str, biz_params: dict = None,
              method: str = 'POST', require_token: bool = False) -> dict:
        """Call an Alibaba Open Platform API.

        All endpoints use GOP protocol: POST /rest{api_path}
        Common params in URL query, business params in POST body.
        api_path must have leading slash (e.g. /auth/token/create).

        Some endpoints accept GET — pass method='GET' to use query params only.
        """
        if not self.is_configured:
            raise RuntimeError("Alibaba API not configured (need ALIBABA_APP_KEY + ALIBABA_APP_SECRET)")

        # Auto-refresh expired token
        if require_token and self.refresh_token and not self.has_valid_token:
            self.refresh_access_token()

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
        common['sign'] = self._sign(api_path, all_params)

        url = f"{API_BASE}/rest{api_path}?{urlencode(common)}"

        if method.upper() == 'GET':
            # GET: business params go in URL query alongside common params
            full_url = f"{url}&{urlencode(biz_params)}"
            resp = httpx.get(full_url, headers={'Accept': 'application/json'}, timeout=30)
        else:
            # POST: business params in body
            resp = httpx.post(
                url,
                data=urlencode(biz_params),
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                timeout=30,
            )

        resp.raise_for_status()
        return resp.json()

    def _parse_response(self, data: dict, api_name: str = '') -> dict:
        """Parse API response, unwrapping GOP envelope."""
        # Unwrap gopResponseBody
        if data.get('gopResponseBody'):
            try:
                data = json.loads(data['gopResponseBody'])
            except (json.JSONDecodeError, TypeError):
                pass

        # Check for ISV error
        if data.get('type') == 'ISV':
            raise RuntimeError(f"Alibaba API error [{data.get('code')}]: {data.get('message')}")

        # Check GOP error code
        code = data.get('gopErrorCode', '0')
        if code and str(code) != '0':
            raise RuntimeError(f"Alibaba API error [{code}]: {data.get('gopErrorMessage', data)}")

        # Unwrap TOP-style response key
        if api_name:
            response_key = api_name.replace('.', '_').replace('/', '_') + '_response'
            # Also try without slashes
            response_key_alt = api_name.lstrip('/').replace('.', '_').replace('/', '_') + '_response'
            for key in (response_key, response_key_alt):
                if key in data:
                    inner = data[key]
                    rsp_code = inner.get('rsp_code', inner.get('code', ''))
                    rsp_msg = inner.get('rsp_msg', inner.get('msg', ''))
                    if rsp_code and str(rsp_code) not in ('200', '0', ''):
                        raise RuntimeError(f"Alibaba API error [{rsp_code}]: {rsp_msg}")
                    if inner.get('error_response'):
                        error = inner['error_response']
                        raise RuntimeError(f"Alibaba API error: {error.get('msg', error)}")
                    # Check success field
                    if inner.get('success') is False:
                        raise RuntimeError(f"Alibaba API: {inner.get('message', inner.get('msg', 'Unknown error'))}")
                    return inner

        # Check for top-level error_response
        if 'error_response' in data:
            error = data['error_response']
            raise RuntimeError(f"Alibaba API error: {error.get('msg', data)}")

        return data

    # ── Token exchange ──

    def exchange_code_for_token(self, code: str) -> dict:
        """Exchange authorization code for access/refresh tokens.

        API: /auth/token/create (GOP protocol)
        """
        data = self._call('/auth/token/create', {'code': code})
        result = self._parse_response(data)

        self.access_token = result.get('access_token', '')
        self.refresh_token = result.get('refresh_token', '')
        expires_in = int(result.get('expires_in', 86400))
        self.token_expires_at = int(time.time()) + expires_in - 300

        if not self.access_token:
            raise RuntimeError(f"Alibaba token exchange returned no access_token: {data}")

        self._save_tokens()

        return {
            'access_token': self.access_token[:20] + '...',
            'refresh_token': self.refresh_token[:20] + '...' if self.refresh_token else '',
            'expires_in': expires_in,
            'refresh_expires_in': result.get('refresh_expires_in', 0),
            'account': result.get('account', ''),
            'account_id': result.get('account_id', ''),
            'country': result.get('country', ''),
        }

    def refresh_access_token(self) -> bool:
        """Refresh the access token using the refresh token."""
        if not self.refresh_token:
            logger.warning("Cannot refresh Alibaba token: no refresh_token")
            return False

        try:
            data = self._call('/auth/token/refresh', {'refresh_token': self.refresh_token})
            result = self._parse_response(data)

            self.access_token = result.get('access_token', '')
            new_refresh = result.get('refresh_token', '')
            if new_refresh:
                self.refresh_token = new_refresh
            expires_in = int(result.get('expires_in', 86400))
            self.token_expires_at = int(time.time()) + expires_in - 300

            self._save_tokens()
            logger.info("Alibaba token refreshed (expires in %ds)", expires_in)
            return True
        except Exception as exc:
            logger.error("Alibaba token refresh failed: %s", exc)
            return False

    # ── Product Search ──

    def search_products(self, keywords: str, page_size: int = 20,
                        country: str = 'AU', language: str = 'en') -> list[dict]:
        """Search products on Alibaba.com.

        API: /eco/buyer/product/search (GET)
        Input: param0 as JSON object with keywords, pageSize, etc.
        """
        request_obj = json.dumps({
            'keywords': keywords,
            'pageSize': page_size,
            'country': country,
            'language': language,
        })
        data = self._call('/eco/buyer/product/search', {'param0': request_obj},
                          method='GET', require_token=True)
        result = self._parse_response(data, '/eco/buyer/product/search')

        products = result.get('result', {})
        if isinstance(products, dict):
            items = products.get('products', products.get('items', []))
        elif isinstance(products, list):
            items = products
        else:
            items = []

        return [
            {
                'id': p.get('productId', p.get('id', '')),
                'title': p.get('subject', p.get('title', p.get('productName', ''))),
                'price': float(p.get('price', p.get('unitPrice', p.get('priceRange', {}).get('min', 0))) or 0),
                'min_order': int(p.get('moq', p.get('minOrderQuantity', 0))),
                'image_url': p.get('imageUrl', p.get('mainImage', '')),
                'product_url': p.get('productUrl', p.get('detailUrl', '')),
                'supplier_id': p.get('supplierId', p.get('companyId', '')),
                'supplier_name': p.get('supplierName', p.get('companyName', '')),
                'rating': float(p.get('rating', p.get('score', 0))),
                'country': p.get('country', ''),
            }
            for p in items
        ]

    def list_products(self, keywords: str = '', category_id: str = '',
                      page_size: int = 20, country: str = 'all',
                      sort: str = 'relevance') -> list[dict]:
        """List products on Alibaba.com with filters.

        API: /eco/buyer/product/check (GET)
        """
        request_obj = json.dumps({
            'keywords': keywords,
            'categoryId': category_id,
            'pageSize': page_size,
            'country': country,
            'sort': sort,
        })
        data = self._call('/eco/buyer/product/check', {'query_req': request_obj},
                          method='GET', require_token=True)
        result = self._parse_response(data, '/eco/buyer/product/check')

        products = result.get('result', {})
        if isinstance(products, dict):
            items = products.get('products', products.get('items', []))
        elif isinstance(products, list):
            items = products
        else:
            items = []

        return [
            {
                'id': p.get('productId', p.get('id', '')),
                'title': p.get('subject', p.get('title', '')),
                'price': float(p.get('price', p.get('unitPrice', 0)) or 0),
                'min_order': int(p.get('moq', 0)),
                'image_url': p.get('imageUrl', ''),
                'product_url': p.get('productUrl', ''),
                'is_local': p.get('isLocal', False),
                'country': p.get('country', ''),
            }
            for p in items
        ]

    def get_product_details(self, product_id: str) -> dict:
        """Get product information by product ID.

        API: /alibaba/icbu/product/get/v2
        """
        data = self._call('/alibaba/icbu/product/get/v2',
                          {'product_id': int(product_id)},
                          require_token=True)
        return self._parse_response(data, '/alibaba/icbu/product/get/v2')

    def get_categories(self) -> list[dict]:
        """Fetch Alibaba product categories.

        API: /icbu/product/category/get
        """
        data = self._call('/icbu/product/category/get', require_token=True)
        result = self._parse_response(data, '/icbu/product/category/get')
        return result.get('categories', result.get('data', []))

    # ── Freight ──

    def calculate_freight(self, product_id: str, country: str = 'AU',
                          quantity: int = 1, zip_code: str = '',
                          dispatch_location: str = 'CN') -> dict:
        """Estimate basic freight cost for a product.

        API: /shipping/freight/calculate
        """
        data = self._call('/shipping/freight/calculate', {
            'product_id': int(product_id),
            'destination_country': country,
            'quantity': quantity,
            'zip_code': zip_code,
            'dispatch_location': dispatch_location,
        }, require_token=True)
        return self._parse_response(data, '/shipping/freight/calculate')

    def calculate_freight_advanced(self, product_list: list[dict], country: str = 'AU',
                                   address: dict = None, company_id: str = '') -> dict:
        """Advanced freight calculation with address details.

        API: /order/freight/calculate
        product_list: [{'productId': 123, 'quantity': 1, 'skuId': ''}, ...]
        address: {'firstName', 'lastName', 'zipCode', 'state', 'city', 'addressLine1', 'country'}
        """
        logistics_list = []
        for item in product_list:
            entry = {
                'productId': item.get('product_id', item.get('productId')),
                'quantity': item.get('quantity', 1),
            }
            if item.get('sku_id') or item.get('skuId'):
                entry['skuId'] = item.get('sku_id', item.get('skuId'))
            logistics_list.append(entry)

        params = {
            'destination_country': country,
            'logistics_product_list': json.dumps(logistics_list),
        }
        if address:
            params['address'] = json.dumps(address)
        if company_id:
            params['e_company_id'] = company_id

        data = self._call('/order/freight/calculate', params, require_token=True)
        return self._parse_response(data, '/order/freight/calculate')

    # ── Orders ──

    def create_order(self, product_list: list[dict], logistics: dict,
                     channel_refer_id: str = '', remark: str = '',
                     attachments: list = None) -> dict:
        """Create a BuyNow order on Alibaba.

        API: /buynow/order/create
        product_list: [{'productId': 123, 'quantity': 1, 'price': 10.5, 'skuId': ''}, ...]
        logistics: {'fullName', 'phone', 'zipCode', 'state', 'city',
                     'addressLine1', 'addressLine2', 'country'}
        channel_refer_id: your internal order ID for tracking
        """
        params = {
            'product_list': json.dumps(product_list),
            'logistics_detail': json.dumps(logistics),
            'channel_refer_id': channel_refer_id,
        }
        if remark:
            params['remark'] = remark
        if attachments:
            params['attachments'] = json.dumps(attachments)

        data = self._call('/buynow/order/create', params, require_token=True)
        result = self._parse_response(data, '/buynow/order/create')
        return result.get('value', result)

    def get_order(self, order_id: str, language: str = 'en') -> dict:
        """Get order details.

        API: /alibaba/order/get
        """
        data = self._call('/alibaba/order/get', {
            'e_trade_id': order_id,
            'language': language,
        }, require_token=True)
        return self._parse_response(data, '/alibaba/order/get').get('value', {})

    def list_orders(self, role: str = 'buyer', status: str = '',
                    page_size: int = 20, start_page: int = 0) -> dict:
        """List orders.

        API: /alibaba/order/list
        """
        params = {
            'role': role,
            'page_size': page_size,
            'start_page': start_page,
        }
        if status:
            params['status'] = status

        data = self._call('/alibaba/order/list', params, require_token=True)
        return self._parse_response(data, '/alibaba/order/list').get('value', {})

    def track_order(self, trade_id: str) -> dict:
        """Track shipment logistics for an order.

        API: /order/logistics/tracking/get
        """
        data = self._call('/order/logistics/tracking/get', {
            'trade_id': int(trade_id),
        }, require_token=True)
        return self._parse_response(data, '/order/logistics/tracking/get')
