"""Python wrapper for the AliExpress IOP SDK CLI jar.

Calls iop-cli.jar via subprocess with JSON args, returns parsed response.
Used by aliexpress.py for affiliate API calls (product search, detail, hot products).
"""

import json
import logging
import os
import shutil
import subprocess

logger = logging.getLogger(__name__)

CLI_JAR = os.path.join(os.path.dirname(__file__), 'iop-cli.jar')

# Find java binary
def _find_java() -> str:
    """Locate the java binary."""
    java_home = os.environ.get('JAVA_HOME', '')
    if java_home:
        candidate = os.path.join(java_home, 'bin', 'java')
        if os.path.isfile(candidate):
            return candidate
        candidate = candidate + '.exe'
        if os.path.isfile(candidate):
            return candidate
    return shutil.which('java') or 'java'


def sdk_call(action: str, params: dict, access_token: str = '') -> dict:
    """Call the IOP SDK CLI jar with JSON args, return parsed response.

    Args:
        action: One of 'affiliate_search', 'affiliate_detail', 'affiliate_hotproduct'
        params: Dict of API parameters (all values as strings)
        access_token: Optional OAuth access token (empty string for no auth)

    Returns:
        Parsed JSON response dict from the API

    Raises:
        RuntimeError: If java not found, jar missing, or SDK returns an error
    """
    java = _find_java()
    if not os.path.isfile(CLI_JAR):
        raise FileNotFoundError(f"IOP SDK CLI jar not found: {CLI_JAR}")

    payload = {
        'action': action,
        'app_key': os.environ.get('ALIEXPRESS_APP_KEY', ''),
        'app_secret': os.environ.get('ALIEXPRESS_APP_SECRET', ''),
        'params': json.dumps(params),
    }
    if access_token:
        payload['access_token'] = access_token

    try:
        result = subprocess.run(
            [java, '-jar', CLI_JAR],
            input=json.dumps(payload),
            capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        raise RuntimeError("Java not found. Install JDK or set JAVA_HOME.")
    except subprocess.TimeoutExpired:
        raise RuntimeError("IOP SDK CLI timed out after 30 seconds")

    if result.returncode != 0:
        raise RuntimeError(f"IOP SDK CLI error: {result.stderr.strip()}")

    output = result.stdout.strip()
    if not output:
        raise RuntimeError("IOP SDK CLI returned empty response")

    return json.loads(output)
