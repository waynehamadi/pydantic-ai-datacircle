"""A Pydantic AI toolset for Datacircle's open API (https://api.datacircle.dev/v1): find the best GTM APIs, no key."""

from pydantic_ai_datacircle.toolset import Datacircle, datacircle_toolset

__version__ = "0.1.0"
__all__ = ["datacircle_toolset", "Datacircle", "__version__"]
