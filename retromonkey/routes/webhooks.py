from flask import Blueprint, request, jsonify

webhook_bp = Blueprint('webhooks', __name__)


@webhook_bp.route('/webhooks/ebay', methods=['POST'])
def ebay_webhook():
    data = request.json
    notification = data.get('notification', {})
    event_type = notification.get('metadata', {}).get('eventType')

    if event_type == 'ORDER_CREATED':
        order_id = notification.get('data', {}).get('orderId')
        # TODO: trigger order processing workflow

    return jsonify({'status': 'ok'}), 200
