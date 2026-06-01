"""AliExpress API connector — product search, order creation, tracking.

Uses the AliExpress Dropshipping API (AppKey: 535696).
Env vars: ALIEXPRESS_APP_KEY, ALIEXPRESS_APP_SECRET, ALIEXPRESS_ACCESS_TOKEN
"""

import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

API_BASE = "https://api-sg.aliexpress.com/openapi"


class AliExpressConnector:
    """Wrapper for the AliExpress Dropshipping API."""

    def __init__(self):
        self.app_key = os.environ.get('ALIEXPRESS_APP_KEY', '')
        self.app_secret = os.environ.get('ALIEXPRESS_APP_SECRET', '')
        self.access_token = os.environ.get('ALIEXPRESS_ACCESS_TOKEN', '')

    @property
    def is_configured(self) -> bool:
        return bool(self.app_key and self.app_secret)

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

    def _call(self, method: str, params: dict = None) -> dict:
        """Make an API call and return parsed JSON."""
        if not self.is_configured:
            raise RuntimeError("AliExpress API not configured (missing ALIEXPRESS_APP_KEY or ALIEXPRESS_APP_SECRET)")

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
        """Place a dropship order on AliExpress.

        Parameters
        ----------
        product_id : str
            AliExpress product ID.
        address : dict
            Shipping address with keys: first_name, last_name, phone,
            address_line_1, city, state, zip, country (2-letter code).
        quantity : int
            Number of units.
        """
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
        })

    def get_order_detail(self, order_id: str) -> dict:
        """Get full order detail."""
        return self._call('aliexpress.dropship.order.get', {
            'order_id': order_id,
        })
