from .. import config
from .base import Provider


def make_provider() -> Provider:
    if config.PROVIDER == "sogni":
        from .sogni import SogniProvider
        return SogniProvider()
    from .mock import MockProvider
    return MockProvider()
