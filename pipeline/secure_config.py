"""
Secure Configuration — Environment variable and secret management.

Provides secure access to sensitive configuration values like API keys,
tokens, and passwords through environment variables or .env files.
NEVER store secrets in source code or commit them to version control.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def get_env(
    key: str,
    default: Optional[str] = None,
    required: bool = False,
) -> Optional[str]:
    """Retrieve an environment variable securely.

    Args:
        key: The environment variable name.
        default: Fallback value if the variable is not set.
        required: If True and the variable is missing, raise EnvironmentError.

    Returns:
        The value of the environment variable or the default.

    Raises:
        EnvironmentError: If *required* is True and the variable is not set.
    """
    value = os.environ.get(key, default)
    if required and value is None:
        raise EnvironmentError(
            f"Required environment variable '{key}' is not set. "
            "Please set it via your shell or a .env file."
        )
    return value


def get_yahoo_finance_proxy() -> Optional[str]:
    """Get Yahoo Finance proxy from environment.

    Reads YAHOO_FINANCE_PROXY environment variable for regions where
    Yahoo Finance is blocked or rate-limited.

    Returns:
        Proxy URL string or None if not configured.
    """
    return get_env("YAHOO_FINANCE_PROXY")


def get_api_token(service: str) -> Optional[str]:
    """Get API token for a specific service from environment.

    Expects the variable name in format: {SERVICE}_API_TOKEN
    Example: YAHOO_FINANCE_API_TOKEN, ALPHA_VANTAGE_API_TOKEN

    Args:
        service: Service identifier (e.g., "yahoo_finance").

    Returns:
        API token string or None if not configured.
    """
    env_key = f"{service.upper()}_API_TOKEN"
    return get_env(env_key)


def load_dotenv(path: str | Path = ".env") -> int:
    """Load environment variables from a .env file.

    This is a lightweight loader that does not require the python-dotenv
    package. It reads key=value pairs from the specified file and
    injects them into os.environ.

    Args:
        path: Path to the .env file.

    Returns:
        Number of variables loaded.

    Note:
        The .env file must NOT be committed to version control.
        It is included in .gitignore by default.
    """
    env_path = Path(path)
    if not env_path.exists():
        return 0

    count = 0
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("\"'")
                if key and not os.environ.get(key):
                    os.environ[key] = value
                    count += 1
    return count


def validate_secrets() -> list[str]:
    """Validate that required secrets are configured.

    Checks for commonly required environment variables and returns
    a list of missing keys.

    Returns:
        List of missing environment variable names. Empty if all present.
    """
    required_keys = []
    optional_checks = {
        "YAHOO_FINANCE_PROXY": "Yahoo Finance proxy (optional for blocked regions)",
    }

    missing = []
    for key in required_keys:
        if not os.environ.get(key):
            missing.append(key)

    return missing
