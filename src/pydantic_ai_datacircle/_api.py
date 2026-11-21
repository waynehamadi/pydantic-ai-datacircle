"""One HTTPS GET to Datacircle's open API (https://api.datacircle.dev/v1), no key, and what its answers are cut to for a model."""

import asyncio
import re
import unicodedata
from typing import Any, Dict, List, Optional

import httpx

BASE_URL = "https://api.datacircle.dev/v1"
USER_AGENT = "pydantic-ai-datacircle/0.1.0"

# A plan holds about 90 keys (its terms of use, its aggregators...): the tools keep the ones that choose a plan, the rest is on its page.
PLAN_KEYS = ["api", "rank", "provider", "plan", "score", "perThousand", "notFoundPerThousand", "billing", "pay",
             "currency", "units", "unit", "strengths", "latencyMs", "page", "pricingPage", "docs"]
API_KEYS = ["api", "slug", "plans", "providers", "best", "bestPage", "sheetPage"]


class DatacircleError(Exception):
    """The API's refusal in its own words, or why it could not be reached: a tool gives it to the model as its answer."""


def brief(item: Dict[str, Any], keys: List[str] = PLAN_KEYS) -> Dict[str, Any]:
    return {key: item[key] for key in keys if item.get(key) is not None}


def slug(value: Any) -> str:
    """The API's rule for a slug: the name in lowercase letters and digits, the rest a hyphen."""
    plain = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    plain = "".join(char for char in plain if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")


def _words(answer: httpx.Response) -> str:
    """A refusal's words: the API's error, with every slug when the slug was unknown."""
    try:
        parsed = answer.json()
        if parsed.get("slugs"):
            return f"{parsed['error']}; the slugs: {', '.join(parsed['slugs'])}"
        return str(parsed.get("error", answer.text))
    except (ValueError, KeyError, TypeError, AttributeError):
        return answer.text


async def get(path: str, params: Optional[Dict[str, Any]] = None, base_url: str = BASE_URL, timeout: float = 30,
              client: Optional[httpx.AsyncClient] = None) -> Any:
    """The API's JSON answer, or a DatacircleError with its words: an unknown slug's answer lists every slug."""
    query = {key: value for key, value in (params or {}).items() if value not in (None, "")}
    url = f"{base_url.rstrip('/')}{path}"
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    own = client is None
    if own:
        client = httpx.AsyncClient(follow_redirects=True)
    try:
        for attempt in range(2):
            try:
                answer = await client.get(url, params=query, headers=headers, timeout=timeout)
            except httpx.HTTPError as error:
                raise DatacircleError(f"Datacircle's API could not be reached: {error!r}") from None
            if answer.status_code == 429:
                if attempt:
                    break
                try:
                    wait = int(answer.headers.get("Retry-After") or 30)
                except ValueError:
                    wait = 30
                await asyncio.sleep(min(max(wait, 1), 60))
                continue
            if answer.status_code >= 400:
                raise DatacircleError(f"Datacircle's API answered {answer.status_code}: {_words(answer)[:3000]}")
            try:
                return answer.json()
            except ValueError as error:
                raise DatacircleError(f"Datacircle's API gave no JSON: {error}") from None
        raise DatacircleError("Datacircle's API answered 429 twice: wait a minute and call again")
    finally:
        if own:
            await client.aclose()
