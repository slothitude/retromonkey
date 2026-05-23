import requests as http_requests
from .base import BaseConnector


class AmazonConnector(BaseConnector):
    MARKETPLACE_NAME = 'Amazon'

    LWA_URL = 'https://sellercentral.amazon.com/services/o2/token'
    SP_API_BASE = 'https://sellingpartnerapi-na.amazon.com'

    def __init__(self, marketplace_record, config):
        super().__init__(marketplace_record, config)
        self.seller_id = config.get('AMAZON_SELLER_ID', '')
        self.lwa_client_id = config.get('AMAZON_LWA_CLIENT_ID', '')
        self.lwa_client_secret = config.get('AMAZON_LWA_CLIENT_SECRET', '')
        self.aws_access_key = config.get('AMAZON_AWS_ACCESS_KEY', '')
        self.aws_secret_key = config.get('AMAZON_AWS_SECRET_KEY', '')
        self.role_arn = config.get('AMAZON_ROLE_ARN', '')
        self._tokens = marketplace_record.credentials if marketplace_record and marketplace_record.credentials else {}

    def authenticate(self) -> dict:
        resp = http_requests.post(self.LWA_URL, data={
            'grant_type': 'refresh_token',
            'refresh_token': self._tokens.get('refresh_token', ''),
            'client_id': self.lwa_client_id,
            'client_secret': self.lwa_client_secret,
        })
        resp.raise_for_status()
        self._tokens.update(resp.json())
        self.marketplace.credentials = self._tokens
        return self._tokens

    def is_authenticated(self) -> bool:
        return bool(self._tokens and self._tokens.get('access_token'))

    def _sign_request(self, method, path, headers, body=''):
        pass  # Uses requests-aws4auth

    def list_item(self, product, listing_data):
        raise NotImplementedError("Amazon SP-API listing requires full AWS Sig v4 implementation")

    def update_listing(self, listing, update_data):
        raise NotImplementedError()

    def end_listing(self, listing):
        raise NotImplementedError()

    def get_orders(self, filters=None):
        raise NotImplementedError()

    def get_order(self, external_order_id):
        raise NotImplementedError()

    def ship_order(self, external_order_id, carrier, tracking_number):
        raise NotImplementedError()

    def get_inventory(self):
        raise NotImplementedError()

    def search(self, query, filters=None):
        raise NotImplementedError()

    def get_pricing(self, asin: str) -> dict:
        raise NotImplementedError()
