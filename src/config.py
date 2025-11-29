"""
Configuration Management
========================

Loads API keys from environment variables or secrets file.
Priority: Environment variables > config_secrets.py

Usage:
    # Option 1: Set environment variable (recommended)
    export WU_API_KEY='your_key_here'
    
    # Option 2: Create src/config_secrets.py (gitignored)
    # Copy config_secrets.example.py to config_secrets.py and add your keys
"""

import os
from typing import Optional

# Try to import from secrets file (gitignored)
try:
    from .config_secrets import WU_API_KEY as WU_API_KEY_SECRET, ASOS_API_KEY as ASOS_API_KEY_SECRET
except (ImportError, ValueError):
    # ValueError can occur when running as script instead of module
    try:
        import sys
        from pathlib import Path
        config_secrets_path = Path(__file__).parent / 'config_secrets.py'
        if config_secrets_path.exists():
            import importlib.util
            spec = importlib.util.spec_from_file_location("config_secrets", config_secrets_path)
            config_secrets = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(config_secrets)
            WU_API_KEY_SECRET = getattr(config_secrets, 'WU_API_KEY', None)
            ASOS_API_KEY_SECRET = getattr(config_secrets, 'ASOS_API_KEY', None)
        else:
            WU_API_KEY_SECRET = None
            ASOS_API_KEY_SECRET = None
    except Exception:
        WU_API_KEY_SECRET = None
        ASOS_API_KEY_SECRET = None


# ============================================================================
# API KEY GETTERS
# ============================================================================

def get_wu_api_key() -> Optional[str]:
    """
    Get Weather Underground API key.
    Priority: Environment variable > config_secrets.py
    """
    # Priority 1: Environment variable
    api_key = os.getenv('WU_API_KEY')
    if api_key:
        return api_key
    
    # Priority 2: Secrets file
    if WU_API_KEY_SECRET and WU_API_KEY_SECRET != 'your_key_here':
        return WU_API_KEY_SECRET
    
    return None


def get_asos_api_key() -> Optional[str]:
    """
    Get ASOS API key.
    Priority: Environment variable > config_secrets.py
    """
    # Priority 1: Environment variable
    api_key = os.getenv('ASOS_API_KEY')
    if api_key:
        return api_key
    
    # Priority 2: Secrets file
    if ASOS_API_KEY_SECRET and ASOS_API_KEY_SECRET != 'your_key_here':
        return ASOS_API_KEY_SECRET
    
    return None
