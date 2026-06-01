import time
import requests as http_requests
from datetime import datetime
from .base import BaseConnector


class EbayConnector(BaseConnector):
    MARKETPLACE_NAME = 'eBay'

    BASE_URLS = {
        'production': 'https://api.ebay.com',
        'sandbox': 'https://api.sandbox.ebay.com',
    }

    AUTH_URLS = {
        'production': 'https://auth.ebay.com',
        'sandbox': 'https://auth.sandbox.ebay.com',
    }

    def __init__(self, marketplace_record, config):
        super().__init__(marketplace_record, config)
        env = config.get('EBAY_ENV', 'sandbox')
        self.base_url = self.BASE_URLS[env]
        self.auth_url = self.AUTH_URLS[env]
        self.client_id = config.get('EBAY_CLIENT_ID', '')
        self.client_secret = config.get('EBAY_CLIENT_SECRET', '')
        self.dev_id = config.get('EBAY_DEV_ID', '')
        self.redirect_uri = config.get('EBAY_REDIRECT_URI', '')
        self._tokens = marketplace_record.credentials if marketplace_record and marketplace_record.credentials else {}

    def get_auth_url(self, state: str = '') -> str:
        scopes = (
            'https://api.ebay.com/oauth/api_scope/sell.inventory'
            ' https://api.ebay.com/oauth/api_scope/sell.fulfillment'
            ' https://api.ebay.com/oauth/api_scope/sell.marketing'
            ' https://api.ebay.com/oauth/api_scope/commerce.identity.readonly'
        )
        return (
            f"{self.auth_url}/oauth2/authorize"
            f"?client_id={self.client_id}"
            f"&response_type=code"
            f"&redirect_uri={self.redirect_uri}"
            f"&scope={scopes.replace(' ', '%20')}"
            f"&state={state}"
        )

    def exchange_code(self, code: str) -> dict:
        resp = http_requests.post(
            f"{self.base_url}/identity/v1/oauth2/token",
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            data={
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': self.redirect_uri,
            },
            auth=(self.client_id, self.client_secret)
        )
        resp.raise_for_status()
        tokens = resp.json()
        tokens['expires_at'] = time.time() + tokens.get('expires_in', 7200)
        self._tokens = tokens
        self.marketplace.credentials = tokens
        return tokens

    def _get_user_token(self) -> str:
        if not self._tokens or not self._tokens.get('access_token'):
            raise Exception("eBay not authenticated. Complete OAuth flow first.")
        if time.time() > self._tokens.get('expires_at', 0) - 300:
            self._refresh_token()
        return self._tokens['access_token']

    def _refresh_token(self) -> None:
        resp = http_requests.post(
            f"{self.base_url}/identity/v1/oauth2/token",
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            data={
                'grant_type': 'refresh_token',
                'refresh_token': self._tokens['refresh_token'],
                'scope': (
                    'https://api.ebay.com/oauth/api_scope/sell.inventory'
                    ' https://api.ebay.com/oauth/api_scope/sell.fulfillment'
                    ' https://api.ebay.com/oauth/api_scope/sell.marketing'
                )
            },
            auth=(self.client_id, self.client_secret)
        )
        resp.raise_for_status()
        new_tokens = resp.json()
        new_tokens['expires_at'] = time.time() + new_tokens.get('expires_in', 7200)
        self._tokens.update(new_tokens)
        self.marketplace.credentials = self._tokens

    def _get_client_token(self) -> str:
        resp = http_requests.post(
            f"{self.base_url}/identity/v1/oauth2/token",
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            data={
                'grant_type': 'client_credentials',
                'scope': 'https://api.ebay.com/oauth/api_scope',
            },
            auth=(self.client_id, self.client_secret)
        )
        resp.raise_for_status()
        return resp.json()['access_token']

    def _headers(self, use_client_token=False) -> dict:
        token = self._get_client_token() if use_client_token else self._get_user_token()
        return {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Content-Language': 'en-AU',
        }

    def authenticate(self) -> dict:
        return self._tokens

    def is_authenticated(self) -> bool:
        return bool(self._tokens and self._tokens.get('access_token'))

    def list_item(self, product, listing_data: dict) -> dict:
        sku = product.sku

        # Step 1: Create/Replace Inventory Item
        self._rate_limit('inventory_item')
        resp = http_requests.put(
            f"{self.base_url}/sell/inventory/v1/inventory_item/{sku}",
            headers=self._headers(),
            json={
                'sku': sku,
                'product': {
                    'title': listing_data['title'],
                    'description': product.description or '',
                    'aspects': listing_data.get('item_specifics', {}),
                    'imageUrls': listing_data.get('images', []),
                    'condition': listing_data.get('condition', 'NEW'),
                },
                'condition': listing_data.get('condition', 'NEW'),
                'packageWeightAndSize': listing_data.get('package_info'),
                'availability': {
                    'shipToLocationAvailability': {
                        'quantity': listing_data['quantity']
                    }
                },
            }
        )
        if resp.status_code >= 400:
            raise Exception(f"eBay inventory error {resp.status_code}: {resp.text[:500]}")

        # Step 2: Create Offer
        self._rate_limit('offer')
        offer_resp = http_requests.post(
            f"{self.base_url}/sell/inventory/v1/offer",
            headers=self._headers(),
            json={
                'sku': sku,
                'marketplaceId': 'EBAY_AU',
                'format': 'FIXED_PRICE',
                'listingDescription': product.description or listing_data['title'],
                'availableQuantity': listing_data['quantity'],
                'categoryId': listing_data.get('category_id'),
                'merchantLocationKey': listing_data.get('merchant_location_key', 'merch_loc_1'),
                'listingPolicies': listing_data.get('listing_policies', {
                    'paymentPolicyId': self.config.get('EBAY_PAYMENT_POLICY_ID', ''),
                    'returnPolicyId': self.config.get('EBAY_RETURN_POLICY_ID', ''),
                    'fulfillmentPolicyId': self.config.get('EBAY_FULFILLMENT_POLICY_ID', ''),
                }),
                'pricingSummary': {
                    'price': {'value': str(listing_data['price']), 'currency': 'AUD'}
                }
            }
        )
        if offer_resp.status_code >= 400:
            raise Exception(f"eBay offer error {offer_resp.status_code}: {offer_resp.text[:500]}")
        offer_id = offer_resp.json()['offerId']

        # Step 3: Publish
        self._rate_limit('publish')
        pub_resp = http_requests.post(
            f"{self.base_url}/sell/inventory/v1/offer/{offer_id}/publish/",
            headers=self._headers()
        )
        if pub_resp.status_code >= 400:
            raise Exception(f"eBay publish error {pub_resp.status_code}: {pub_resp.text[:500]}")
        listing_id = pub_resp.json().get('listingId', '')

        return {
            'external_id': listing_id,
            'offer_id': offer_id,
            'status': 'active',
            'url': f"https://www.ebay.com/itm/{listing_id}" if listing_id else None,
        }

    def bulk_list(self, items: list[dict]) -> list[dict]:
        results = []
        for item in items:
            try:
                result = self.list_item(item['product'], item['listing_data'])
                results.append({'success': True, **result})
            except Exception as e:
                results.append({'success': False, 'error': str(e), 'sku': item['product'].sku})
        return results

    def update_listing(self, listing, update_data: dict) -> dict:
        offer_id = listing.external_id

        # If quantity is being updated, also update the inventory item
        qty = update_data.get('availableQuantity')
        if qty is not None:
            sku = listing.product.sku if listing.product else None
            if sku:
                self._rate_limit('inventory_item_update')
                http_requests.put(
                    f"{self.base_url}/sell/inventory/v1/inventory_item/{sku}",
                    headers=self._headers(),
                    json={
                        'availability': {
                            'shipToLocationAvailability': {
                                'quantity': qty
                            }
                        }
                    }
                )

        self._rate_limit('offer_update')
        resp = http_requests.put(
            f"{self.base_url}/sell/inventory/v1/offer/{offer_id}",
            headers=self._headers(),
            json=update_data
        )
        resp.raise_for_status()
        return {'status': 'updated'}

    def end_listing(self, listing) -> dict:
        offer_id = listing.external_id
        self._rate_limit('withdraw')
        resp = http_requests.post(
            f"{self.base_url}/sell/inventory/v1/offer/{offer_id}/withdraw",
            headers=self._headers()
        )
        resp.raise_for_status()
        return {'status': 'ended'}

    def get_inventory(self) -> list[dict]:
        self._rate_limit('get_inventory')
        resp = http_requests.get(
            f"{self.base_url}/sell/inventory/v1/inventory_item?limit=100&offset=0",
            headers=self._headers()
        )
        resp.raise_for_status()
        items = resp.json().get('inventoryItems', [])
        return [{
            'sku': i.get('sku'),
            'quantity': i.get('totalQuantity', 0),
            'title': i.get('product', {}).get('title', ''),
            'condition': i.get('condition', ''),
        } for i in items]

    def get_orders(self, filters: dict = None) -> list[dict]:
        params = {'limit': 50}
        if filters:
            filter_parts = []
            if filters.get('status'):
                status_map = {'pending': 'NOT_STARTED', 'processing': 'IN_PROGRESS', 'shipped': 'FULFILLED'}
                ebay_status = status_map.get(filters['status'], 'NOT_STARTED')
                filter_parts.append(f"orderfulfillmentstatus:{ebay_status}")
            if filters.get('date_from'):
                filter_parts.append(f"creationdate:[{filters['date_from']}..]")
            if filter_parts:
                params['filter'] = ','.join(filter_parts)

        self._rate_limit('orders')
        resp = http_requests.get(
            f"{self.base_url}/sell/fulfillment/v1/order",
            headers=self._headers(),
            params=params
        )
        resp.raise_for_status()
        orders = resp.json().get('orders', [])
        return [self._parse_order(o) for o in orders]

    def _parse_order(self, raw: dict) -> dict:
        items = []
        for li in raw.get('lineItems', []):
            qty = li.get('quantity', 1)
            line_total = float(li.get('total', {}).get('value', 0))
            unit_price = round(line_total / qty, 2) if qty else line_total
            items.append({
                'sku': li.get('sku', ''),
                'quantity': qty,
                'unit_price': unit_price,
                'title': li.get('title', ''),
            })

        # Extract shipping address
        shipping = raw.get('shippingDetails', {})
        address = shipping.get('shipTo', {}) if isinstance(shipping, dict) else {}
        shipping_address = {
            'name': address.get('fullName', ''),
            'address_line_1': address.get('addressLine1', ''),
            'address_line_2': address.get('addressLine2', ''),
            'city': address.get('city', ''),
            'state': address.get('stateOrProvince', ''),
            'postcode': address.get('postalCode', ''),
            'country': address.get('country', ''),
        }

        return {
            'external_order_id': raw.get('orderId', ''),
            'buyer_name': raw.get('buyer', {}).get('username', ''),
            'buyer_email': '',
            'status': self._map_order_status(raw.get('orderFulfillmentStatus', '')),
            'total': float(raw.get('pricingSummary', {}).get('total', {}).get('value', 0)),
            'currency': raw.get('pricingSummary', {}).get('total', {}).get('currency', 'AUD'),
            'items': items,
            'ordered_at': raw.get('creationDate', ''),
            'shipping_address': shipping_address,
        }

    def _map_order_status(self, ebay_status: str) -> str:
        return {'NOT_STARTED': 'pending', 'IN_PROGRESS': 'processing', 'FULFILLED': 'shipped'}.get(ebay_status, 'pending')

    def get_order(self, external_order_id: str) -> dict:
        self._rate_limit('order')
        resp = http_requests.get(
            f"{self.base_url}/sell/fulfillment/v1/order/{external_order_id}",
            headers=self._headers()
        )
        resp.raise_for_status()
        return self._parse_order(resp.json())

    def ship_order(self, external_order_id: str, carrier: str, tracking_number: str) -> dict:
        self._rate_limit('ship')
        resp = http_requests.post(
            f"{self.base_url}/sell/fulfillment/v1/order/{external_order_id}/shipping_fulfillment",
            headers=self._headers(),
            json={
                'lineItems': [],
                'shipmentTrackingNumber': tracking_number,
                'shippingCarrierCode': carrier,
            }
        )
        resp.raise_for_status()
        return {'status': 'shipped', 'fulfillment_id': resp.json().get('fulfillmentId')}

    def search(self, query: str, filters: dict = None) -> list[dict]:
        params = {'q': query, 'limit': 50}
        if filters:
            if filters.get('category'):
                params['category_ids'] = filters['category']
            if filters.get('price_max'):
                params['filter'] = f'price:[..{filters["price_max"]}]'

        self._rate_limit('search')
        resp = http_requests.get(
            f"{self.base_url}/buy/browse/v1/item_summary/search",
            headers=self._headers(use_client_token=True),
            params=params
        )
        resp.raise_for_status()
        items = resp.json().get('itemSummaries', [])
        return [{
            'title': i.get('title'),
            'price': float(i.get('price', {}).get('value', 0)),
            'currency': i.get('price', {}).get('currency', 'AUD'),
            'item_id': i.get('itemId'),
            'url': i.get('itemWebUrl'),
            'seller': i.get('seller', {}).get('username'),
            'condition': i.get('condition'),
        } for i in items]

    def get_category_suggestions(self, title: str) -> list[dict]:
        self._rate_limit('taxonomy')
        resp = http_requests.get(
            f"{self.base_url}/commerce/taxonomy/v1/category_suggestions",
            headers=self._headers(use_client_token=True),
            params={'q': title}
        )
        resp.raise_for_status()
        return resp.json().get('suggestions', [])

    def create_campaign(self, listing_ids: list[str], budget: float, strategy: str = 'CPS', rate: float = 5.0) -> dict:
        self._rate_limit('campaign')
        resp = http_requests.post(
            f"{self.base_url}/sell/marketing/v1/campaign",
            headers=self._headers(),
            json={
                'campaignName': f'Auto_{datetime.now().strftime("%Y%m%d")}',
                'fundingStrategy': {'bidPercentage': str(rate) if strategy == 'CPS' else None, 'budgetType': 'DAILY'},
                'dailyBudget': str(budget),
                'startDate': datetime.now().isoformat(),
                'listingIds': listing_ids,
            }
        )
        resp.raise_for_status()
        return {'campaign_id': resp.json().get('campaignId'), 'status': 'created'}

    def get_traffic_report(self, listing_id: str, date_range: tuple = None) -> dict:
        self._rate_limit('analytics')
        params = {}
        if date_range:
            params['filter'] = f'listingIds:[{listing_id}],dateRange:[{date_range[0]}..{date_range[1]}]'
        resp = http_requests.get(
            f"{self.base_url}/sell/analytics/v1/traffic_report",
            headers=self._headers(),
            params=params
        )
        resp.raise_for_status()
        return resp.json()

    def get_payment_policies(self) -> list[dict]:
        self._rate_limit('account')
        resp = http_requests.get(
            f"{self.base_url}/sell/account/v1/payment_policy",
            headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json().get('paymentPolicies', [])

    def get_return_policies(self) -> list[dict]:
        self._rate_limit('account')
        resp = http_requests.get(
            f"{self.base_url}/sell/account/v1/return_policy",
            headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json().get('returnPolicies', [])

    def get_fulfillment_policies(self) -> list[dict]:
        self._rate_limit('account')
        resp = http_requests.get(
            f"{self.base_url}/sell/account/v1/fulfillment_policy",
            headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json().get('fulfillmentPolicies', [])

    def create_payment_policy(self, name: str = 'RetroMonkey Payment') -> dict:
        self._rate_limit('account')
        resp = http_requests.post(
            f"{self.base_url}/sell/account/v1/payment_policy",
            headers=self._headers(),
            json={
                'name': name,
                'marketplaceId': 'EBAY_AU',
                'paymentMethods': [{'paymentMethodType': 'PERSONAL_CHECK'}],
                'immediatePay': True,
            }
        )
        resp.raise_for_status()
        return resp.json()

    def create_return_policy(self, name: str = 'RetroMonkey Returns') -> dict:
        self._rate_limit('account')
        resp = http_requests.post(
            f"{self.base_url}/sell/account/v1/return_policy",
            headers=self._headers(),
            json={
                'name': name,
                'marketplaceId': 'EBAY_AU',
                'returnsAccepted': True,
                'returnPeriod': {
                    'value': 30,
                    'unit': 'DAY'
                },
                'refundMethod': 'MONEY_BACK',
                'returnShippingCostPayer': 'BUYER',
                'description': '30 day return policy. Buyer pays return shipping.',
            }
        )
        resp.raise_for_status()
        return resp.json()

    def create_fulfillment_policy(self, name: str = 'RetroMonkey Shipping') -> dict:
        self._rate_limit('account')
        resp = http_requests.post(
            f"{self.base_url}/sell/account/v1/fulfillment_policy",
            headers=self._headers(),
            json={
                'name': name,
                'marketplaceId': 'EBAY_AU',
                'handlingTime': {
                    'value': 3,
                    'unit': 'DAY'
                },
                'shippingOptions': [{
                    'optionType': 'DOMESTIC',
                    'costType': 'FLAT_RATE',
                    'shippingServices': [{
                        'shippingServiceCode': 'AU_Regular',
                        'shippingCost': {'value': '0.00', 'currency': 'AUD'},
                        'additionalShippingCost': {'value': '0.00', 'currency': 'AUD'},
                        'shipToLocations': {
                            'regionIncluded': [{'regionName': 'WORLDWIDE'}]
                        },
                    }]
                }],
            }
        )
        resp.raise_for_status()
        return resp.json()

    def ensure_policies(self) -> dict:
        payment = self.get_payment_policies()
        if not payment:
            payment = [self.create_payment_policy()]
        return_policy = self.get_return_policies()
        if not return_policy:
            return_policy = [self.create_return_policy()]
        fulfillment = self.get_fulfillment_policies()
        if not fulfillment:
            fulfillment = [self.create_fulfillment_policy()]
        return {
            'payment_policy_id': payment[0]['paymentPolicyId'],
            'return_policy_id': return_policy[0]['returnPolicyId'],
            'fulfillment_policy_id': fulfillment[0]['fulfillmentPolicyId'],
        }

    def get_seller_dashboard(self) -> dict:
        self._rate_limit('dashboard')
        resp = http_requests.get(
            f"{self.base_url}/sell/analytics/v1/seller_dashboard",
            headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()
