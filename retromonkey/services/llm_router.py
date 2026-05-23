import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class LLMRouter:
    """Routes LLM requests by complexity with fallback chain."""

    MODES = ('auto', 'rule', 'ollama', 'claude')

    def __init__(self, app=None):
        self.default_mode = 'auto'
        self.cost_log = []
        self._ollama_url = 'http://localhost:11434'
        self._claude_key = ''
        if app:
            self._init_app(app)

    def _init_app(self, app):
        self.default_mode = app.config.get('LLM_DEFAULT_MODE', 'auto')
        self._ollama_url = app.config.get('OLLAMA_BASE_URL', 'http://localhost:11434')
        self._claude_key = app.config.get('CLAUDE_API_KEY', '')

    def query(self, prompt: str, mode: str = 'auto', system: str = '',
              max_tokens: int = 1024) -> dict:
        """
        Route and execute LLM query.
        Returns: {'text': str, 'mode_used': str, 'cost': float, 'tokens': int}
        """
        if mode == 'auto':
            mode = self._classify_complexity(prompt)

        if mode == 'rule':
            return {'text': '', 'mode_used': 'rule', 'cost': 0.0, 'tokens': 0}

        # Try primary, fallback on failure
        if mode == 'claude':
            try:
                return self._call_claude(prompt, system, max_tokens)
            except Exception as e:
                logger.warning(f"Claude failed, falling back to ollama: {e}")
                try:
                    return self._call_ollama(prompt, system, max_tokens)
                except Exception as e2:
                    logger.error(f"Ollama also failed: {e2}")
                    return {'text': '', 'mode_used': 'rule', 'cost': 0.0, 'tokens': 0, 'error': str(e)}

        if mode == 'ollama':
            try:
                return self._call_ollama(prompt, system, max_tokens)
            except Exception as e:
                logger.warning(f"Ollama failed, falling back to claude: {e}")
                try:
                    return self._call_claude(prompt, system, max_tokens)
                except Exception as e2:
                    logger.error(f"Claude also failed: {e2}")
                    return {'text': '', 'mode_used': 'rule', 'cost': 0.0, 'tokens': 0, 'error': str(e)}

        return {'text': '', 'mode_used': 'rule', 'cost': 0.0, 'tokens': 0}

    def _call_claude(self, prompt, system, max_tokens) -> dict:
        import anthropic
        client = anthropic.Anthropic(api_key=self._claude_key)
        kwargs = {'model': 'claude-sonnet-4-20250514', 'max_tokens': max_tokens, 'messages': [{'role': 'user', 'content': prompt}]}
        if system:
            kwargs['system'] = system
        resp = client.messages.create(**kwargs)
        text = resp.content[0].text
        # Estimate cost (Sonnet ~$3/MTok input, ~$15/MTok output)
        input_tokens = resp.usage.input_tokens
        output_tokens = resp.usage.output_tokens
        cost = (input_tokens / 1_000_000 * 3) + (output_tokens / 1_000_000 * 15)
        self._log_cost('claude', cost, input_tokens + output_tokens)
        return {'text': text, 'mode_used': 'claude', 'cost': cost, 'tokens': input_tokens + output_tokens}

    def _call_ollama(self, prompt, system, max_tokens) -> dict:
        import requests
        payload = {'model': 'qwen3', 'messages': [], 'stream': False, 'options': {'num_predict': max_tokens}}
        if system:
            payload['messages'].append({'role': 'system', 'content': system})
        payload['messages'].append({'role': 'user', 'content': prompt})
        resp = requests.post(f'{self._ollama_url}/api/chat', json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        text = data.get('message', {}).get('content', '')
        self._log_cost('ollama', 0.0, 0)
        return {'text': text, 'mode_used': 'ollama', 'cost': 0.0, 'tokens': 0}

    def _classify_complexity(self, prompt: str) -> str:
        simple_keywords = ['calculate', 'format', 'extract', 'list', 'count', 'sum', 'sort']
        if len(prompt) < 200:
            for kw in simple_keywords:
                if kw in prompt.lower():
                    return 'ollama'
        complex_keywords = ['analyze', 'recommend', 'generate', 'write', 'create', 'strategy', 'swot']
        for kw in complex_keywords:
            if kw in prompt.lower():
                return 'claude'
        return 'ollama'

    def _log_cost(self, mode, cost, tokens):
        self.cost_log.append({
            'mode': mode, 'cost': cost, 'tokens': tokens,
            'timestamp': datetime.now(timezone.utc)
        })

    def get_daily_cost(self) -> float:
        today = datetime.now(timezone.utc).date()
        return sum(e['cost'] for e in self.cost_log if e['timestamp'].date() == today)
