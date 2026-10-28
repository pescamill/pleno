"""HTTPS context shared by every outbound call.

python.org builds on macOS ship without root certificates; certifi fills that gap when installed.
"""

import ssl

try:
    import certifi
except ImportError:  # system Python with its own trust store
    certifi = None

SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where()) if certifi else ssl.create_default_context()
