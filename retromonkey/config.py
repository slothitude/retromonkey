import os


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-change-in-prod')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Stripe
    STRIPE_PUBLIC_KEY = os.environ.get('STRIPE_PUBLIC_KEY', '')
    STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY', '')
    STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')

    # Store Identity
    SITE_URL = os.environ.get('SITE_URL', 'http://localhost:5000')
    STORE_NAME = os.environ.get('STORE_NAME', 'RetroMonkey')
    STORE_TAGLINE = os.environ.get('STORE_TAGLINE', 'Retro Gaming & Tech')
    STORE_LOGO = os.environ.get('STORE_LOGO', '/static/images/logo.png')
    STORE_THEME = os.environ.get('STORE_THEME', 'neon_noir')
    STORE_CURRENCY = os.environ.get('STORE_CURRENCY', 'AUD')
    STORE_AGENT_TOKEN = os.environ.get('STORE_AGENT_TOKEN', '')  # auth token for agent MCP access
    CURRENCY = 'aud'
    ABN = os.environ.get('ABN', '')
    BUSINESS_NAME = os.environ.get('BUSINESS_NAME', 'RetroMonkey')
    GST_RATE = 0.10  # 10%

    # SMTP (Zoho Mail)
    SMTP_HOST = os.environ.get('SMTP_HOST', '')
    SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
    SMTP_USER = os.environ.get('SMTP_USER', '')
    SMTP_PASS = os.environ.get('SMTP_PASS', '')
    SMTP_FROM = os.environ.get('SMTP_FROM', '')

    # Session security
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'false').lower() == 'true'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'

    # eBay
    EBAY_CLIENT_ID = os.environ.get('EBAY_CLIENT_ID', '')
    EBAY_CLIENT_SECRET = os.environ.get('EBAY_CLIENT_SECRET', '')
    EBAY_DEV_ID = os.environ.get('EBAY_DEV_ID', '')
    EBAY_REDIRECT_URI = os.environ.get('EBAY_REDIRECT_URI', '')
    EBAY_ENV = os.environ.get('EBAY_ENV', os.environ.get('EBAY_ENVIRONMENT', 'sandbox'))
    EBAY_PAYMENT_POLICY_ID = os.environ.get('EBAY_PAYMENT_POLICY_ID', '')
    EBAY_RETURN_POLICY_ID = os.environ.get('EBAY_RETURN_POLICY_ID', '')
    EBAY_FULFILLMENT_POLICY_ID = os.environ.get('EBAY_FULFILLMENT_POLICY_ID', '')
    EBAY_USER_TOKEN = os.environ.get('EBAY_USER_TOKEN', '')

    # Amazon
    AMAZON_SELLER_ID = os.environ.get('AMAZON_SELLER_ID', '')
    AMAZON_LWA_CLIENT_ID = os.environ.get('AMAZON_LWA_CLIENT_ID', '')
    AMAZON_LWA_CLIENT_SECRET = os.environ.get('AMAZON_LWA_CLIENT_SECRET', '')
    AMAZON_AWS_ACCESS_KEY = os.environ.get('AMAZON_AWS_ACCESS_KEY', '')
    AMAZON_AWS_SECRET_KEY = os.environ.get('AMAZON_AWS_SECRET_KEY', '')
    AMAZON_ROLE_ARN = os.environ.get('AMAZON_ROLE_ARN', '')

    # LLM
    CLAUDE_API_KEY = os.environ.get('CLAUDE_API_KEY', '')
    OLLAMA_BASE_URL = os.environ.get('OLLAMA_BASE_URL', 'http://localhost:11434')
    LLM_DEFAULT_MODE = os.environ.get('LLM_DEFAULT_MODE', 'auto')

    # Gmail
    GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')
    GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')
    GMAIL_REDIRECT_URI = os.environ.get('GMAIL_REDIRECT_URI', 'http://localhost:5000/api/intelligence/gmail/callback')
    GOOGLE_PUBSUB_TOPIC = os.environ.get('GOOGLE_PUBSUB_TOPIC', '')
    GOOGLE_GMAIL_WATCH_ENABLED = os.environ.get('GOOGLE_GMAIL_WATCH_ENABLED', 'false').lower() == 'true'

    # Telegram Alerts
    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')
    ALERT_EMAIL = os.environ.get('ALERT_EMAIL', 'aaronjking86@gmail.com')
    ALERT_TELEGRAM_ENABLED = os.environ.get('ALERT_TELEGRAM_ENABLED', 'false').lower() == 'true'

    # Scheduler
    SCHEDULER_ORDER_POLL_INTERVAL = 15
    SCHEDULER_INVENTORY_SYNC_INTERVAL = 30


class DevConfig(Config):
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///retromonkey.db')
    DEBUG = True


class ProdConfig(Config):
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    DEBUG = False
