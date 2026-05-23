from .base import BaseConnector


class KoganConnector(BaseConnector):
    MARKETPLACE_NAME = 'Kogan'

    def __init__(self, marketplace_record, config):
        super().__init__(marketplace_record, config)
        settings = marketplace_record.settings if marketplace_record and marketplace_record.settings else {}
        self.api_base = settings.get('api_url', 'https://api.kogan.com')
        creds = marketplace_record.credentials if marketplace_record and marketplace_record.credentials else {}
        self.api_key = creds.get('api_key', '')

    def authenticate(self) -> dict:
        return {'authenticated': bool(self.api_key)}

    def is_authenticated(self) -> bool:
        return bool(self.api_key)

    def list_item(self, product, listing_data):
        raise NotImplementedError("Kogan API integration pending API documentation")

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
