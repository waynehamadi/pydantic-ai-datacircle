"""A Pydantic AI toolset on Datacircle's open API, https://api.datacircle.dev/v1: no key, no account."""

import urllib.parse
from typing import Annotated, Any, Awaitable, Callable, Dict, Iterable, Literal, Optional

import httpx
from pydantic import Field
from pydantic_ai import Tool
from pydantic_ai.toolsets import FunctionToolset

from pydantic_ai_datacircle import _api

NAMES = ("list_apis", "best_plans", "search_plans", "provider")


async def _answer(make: Callable[[], Awaitable[Dict[str, Any]]]) -> Dict[str, Any]:
    """What the API gave, or {"error": ...} with its words for the model to read and call again."""
    try:
        return await make()
    except _api.DatacircleError as error:
        return {"error": str(error)}


def _best(plans: Any) -> Optional[Dict[str, Any]]:
    """A provider's best plan on an API: its lowest rank, a plan with no score having none."""
    ranked = sorted(plans, key=lambda plan: plan.get("rank") if isinstance(plan.get("rank"), (int, float)) else float("inf"))
    return _api.brief(ranked[0], ["plan", "score", "perThousand", "page"]) if ranked else None


class Datacircle:
    """Datacircle's benchmark of GTM APIs (https://datacircle.dev): every API it lists, who is best for each, every plan
    and each provider's ranks, from its open API. Each method makes one HTTPS GET and gives the answer as a dict, or
    {"error": ...} with the API's words.

    Args:
        base_url: The API's address. Default https://api.datacircle.dev/v1.
        timeout: Seconds each HTTP request may take. Default 30.
        http_client: An httpx.AsyncClient of yours to send the requests (a proxy, your own transport). Default one per call.
    """

    def __init__(self, base_url: str = _api.BASE_URL, timeout: float = 30, http_client: Optional[httpx.AsyncClient] = None):
        self.base_url = base_url
        self.timeout = timeout
        self.http_client = http_client

    async def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return await _api.get(path, params, base_url=self.base_url, timeout=self.timeout, client=self.http_client)

    async def list_apis(self, query: Optional[str] = None, limit: Optional[int] = None) -> Dict[str, Any]:
        """Lists the GTM APIs on Datacircle's sheet, each with its slug, how many plans and providers it has and its
        best plan: the ones whose name holds the most of query's words first. Gives total and up to limit (20) APIs."""

        async def make() -> Dict[str, Any]:
            apis = await self._get("/apis")
            words = [word for word in str(query or "").lower().replace("-", " ").split() if word]
            held = []
            for index, api in enumerate(apis):
                name = f"{api.get('api', '')} {str(api.get('slug', '')).replace('-', ' ')}".lower()
                matched = sum(word in name for word in words)
                if matched or not words:
                    held.append((-matched, index, api))
            found = [_api.brief(api, _api.API_KEYS) for _, _, api in sorted(held, key=lambda h: h[:2])]
            return {"total": len(found), "apis": found[:limit or 20]}

        return await _answer(make)

    async def best_plans(self, slug: str, limit: Optional[int] = None) -> Dict[str, Any]:
        """Gives an API's plans best first by their score out of 100, each with its rank, provider, plan, $ per 1,000
        calls and its page: slug is the API's slug or name, limit 1 to 50 (10)."""

        async def make() -> Dict[str, Any]:
            made = _api.slug(slug)
            if not made:
                raise _api.DatacircleError("Give an API's slug, like 'email-finder': datacircle_list_apis gives every slug")
            answer = await self._get(f"/apis/{urllib.parse.quote(made)}/best", {"limit": limit})
            return {**answer, "plans": [_api.brief(plan) for plan in answer.get("plans") or []]}

        return await _answer(make)

    async def search_plans(self, api: Optional[str] = None, query: Optional[str] = None, sort: Optional[str] = None,
                           limit: Optional[int] = None, offset: Optional[int] = None) -> Dict[str, Any]:
        """Searches every plan, or one API's, by provider or plan name, sorted by score (the default), provider or
        price. Gives total, offset and up to limit (10) plans."""

        async def make() -> Dict[str, Any]:
            params = {"api": api, "query": query, "sort": sort, "limit": limit, "offset": offset}
            answer = await self._get("/plans", params)
            return {**answer, "plans": [_api.brief(plan) for plan in answer.get("plans") or []]}

        return await _answer(make)

    async def provider(self, slug: str) -> Dict[str, Any]:
        """Gives each API one provider sells and its rank on each, with its best plan there: slug is the provider's
        slug or name."""

        async def make() -> Dict[str, Any]:
            made = _api.slug(slug)
            if not made:
                raise _api.DatacircleError("Give a provider's slug or name, like 'bright-data' or 'Bright Data'")
            answer = await self._get(f"/providers/{urllib.parse.quote(made)}")
            apis = [{**_api.brief(entry, ["api", "slug", "rank", "bestPage"]), "plans": len(entry.get("plans") or []),
                     "best": _best(entry.get("plans") or [])} for entry in answer.get("apis") or []]
            return {**answer, "apis": apis}

        return await _answer(make)

    def toolset(self, include: Optional[Iterable[str]] = None, max_retries: Optional[int] = None,
                id: Optional[str] = "datacircle") -> FunctionToolset:
        """The methods as a FunctionToolset for Agent(toolsets=[...]), its tools named datacircle_<method>: all four, or
        those include names (list_apis, best_plans, search_plans, provider)."""
        names = list(NAMES) if include is None else [str(name).removeprefix("datacircle_") for name in include]
        unknown = [name for name in names if name not in NAMES]
        if unknown:
            raise ValueError(f"No such Datacircle tool: {', '.join(unknown)}. The tools: {', '.join(NAMES)}")

        async def list_apis(query: Optional[str] = None,
                            limit: Optional[Annotated[int, Field(ge=1, le=200)]] = None) -> Dict[str, Any]:
            """Datacircle's tool.

            Args:
                query: Words of the API's name or slug, like 'email' or 'linkedin profile': the APIs that hold the most of them come first. Leave it out for the sheet's order.
                limit: How many APIs to give, 1 to 200. 20 when left out: the sheet has about 150.
            """
            return await self.list_apis(query, limit)

        async def best_plans(slug: str, limit: Optional[Annotated[int, Field(ge=1, le=50)]] = None) -> Dict[str, Any]:
            """Datacircle's tool.

            Args:
                slug: The API's slug, like 'email-finder' or 'linkedin-profile', as datacircle_list_apis gives it.
                limit: How many plans to give, 1 to 50. 10 when left out.
            """
            return await self.best_plans(slug, limit)

        async def search_plans(api: Optional[str] = None, query: Optional[str] = None,
                               sort: Optional[Literal["score", "provider", "price"]] = None,
                               limit: Optional[Annotated[int, Field(ge=1, le=50)]] = None,
                               offset: Optional[Annotated[int, Field(ge=0)]] = None) -> Dict[str, Any]:
            """Datacircle's tool.

            Args:
                api: Only this API's plans: its slug, like 'email-finder'. A provider's name goes in query, never here. Leave it out for every API.
                query: Words that must all appear in the provider's or plan's name, like 'bright data'. Leave it out for any.
                sort: score (best first), provider (A to Z) or price ($ per 1,000, lowest first). score when left out.
                limit: How many plans to give, 1 to 50. 10 when left out.
                offset: How many found plans to skip first. 0 when left out.
            """
            return await self.search_plans(api, query, sort, limit, offset)

        async def provider(slug: str) -> Dict[str, Any]:
            """Datacircle's tool.

            Args:
                slug: The provider's slug, like 'bright-data', or its name, like 'Bright Data': the name is made a slug.
            """
            return await self.provider(slug)

        made = {"list_apis": list_apis, "best_plans": best_plans, "search_plans": search_plans, "provider": provider}
        tools = [Tool(made[name], takes_ctx=False, name=f"datacircle_{name}", description=DESCRIPTIONS[name],
                      docstring_format="google", require_parameter_descriptions=True) for name in NAMES if name in names]
        return FunctionToolset(tools, id=id, **({} if max_retries is None else {"max_retries": max_retries}))


PER_THOUSAND = "perThousand is a plan's price of 1,000 items in dollars, pay the plan's whole price in its currency."

DESCRIPTIONS = {
    "list_apis": "Lists the GTM APIs on Datacircle's sheet (https://datacircle.dev), with each API's slug, how many "
                 "plans and providers it has and its best plan. Call it first to find an API's slug. Gives total, the "
                 "APIs found, and apis, up to limit of them.",
    "best_plans": "Gives an API's plans best first by their score out of 100 on Datacircle's benchmark "
                  "(https://datacircle.dev), each with its rank, provider, plan, $ per 1,000 calls and its page: the "
                  "best providers of an API. " + PER_THOUSAND,
    "search_plans": "Searches every plan on Datacircle's sheet (https://datacircle.dev), or one API's, by provider or "
                    "plan name, sorted by score, provider or price. Gives total, offset and up to limit plans. "
                    + PER_THOUSAND,
    "provider": "Gives each API one provider sells and its rank on each on Datacircle's benchmark "
                "(https://datacircle.dev), with its best plan there. For an API's best providers, call "
                "datacircle_best_plans.",
}


def datacircle_toolset(include: Optional[Iterable[str]] = None, base_url: str = _api.BASE_URL, timeout: float = 30,
                       http_client: Optional[httpx.AsyncClient] = None, max_retries: Optional[int] = None,
                       id: Optional[str] = "datacircle") -> FunctionToolset:
    """The Datacircle toolset for Agent(toolsets=[...]): datacircle_list_apis, datacircle_best_plans,
    datacircle_search_plans and datacircle_provider, or those include names. max_retries is how often the model may
    send arguments the tools refuse (the agent's when left out); id names the toolset for durable execution."""
    return Datacircle(base_url, timeout, http_client).toolset(include, max_retries=max_retries, id=id)
