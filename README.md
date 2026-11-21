# pydantic-ai-datacircle

Find the best GTM APIs. We benchmark all the GTM APIs and we put the results on our website: https://datacircle.dev

This package gives [Pydantic AI](https://github.com/pydantic/pydantic-ai) a toolset of four tools on Datacircle's open API, https://api.datacircle.dev/v1. You need no key and no account.

```bash
pip install pydantic-ai-datacircle
```

It needs only `pydantic-ai-slim`; add your model's client, like `pip install "pydantic-ai-slim[anthropic]"` for the example below, or install the whole `pydantic-ai`.

| Tool | What it gives | Call |
| --- | --- | --- |
| `datacircle_list_apis` | Every GTM API on Datacircle, with its slug, number of plans and providers, and its best plan | `GET /apis` |
| `datacircle_best_plans` | One API's plans, best first by score out of 100, each with its rank and price per 1,000 calls | `GET /apis/{slug}/best` |
| `datacircle_search_plans` | Plans by provider or plan name, on every API or one, sorted by score, provider or price | `GET /plans` |
| `datacircle_provider` | The APIs a provider sells and its rank on each | `GET /providers/{slug}` |

## Use

```python
from pydantic_ai import Agent
from pydantic_ai_datacircle import datacircle_toolset

agent = Agent(
    "anthropic:claude-sonnet-5-5",
    instructions="Answer from the datacircle tools.",
    toolsets=[datacircle_toolset()],
)
result = agent.run_sync("Which email finder API is best for under $5 per 1,000?")
print(result.output)
```

Any model Pydantic AI runs works. `datacircle_toolset(include=["best_plans", "provider"])` gives only some of the tools. The toolset is a `FunctionToolset`, so it takes the toolset wrappers (`.prefixed()`, `.filtered()`, `.approval_required()`...) and works with `run`, `run_sync`, `run_stream` and `iter`. Pydantic AI 1.0 and later, Python 3.10 and later.

The same calls without an agent, each giving a dict:

```python
import asyncio
from pydantic_ai_datacircle import Datacircle

print(asyncio.run(Datacircle().best_plans("email-finder", limit=3)))
```

Each plan comes with its rank, provider, plan, score, price per 1,000 (`perThousand`, in dollars) and its page on datacircle.dev, which lists every field. A slug can be a name: `Bright Data` is sent as `bright-data`. An unknown slug comes back as `{"error": ...}` with the API's words (an unknown API's answer lists every slug), so the model can call again; an argument out of range is refused by Pydantic AI before any call, and the model is asked to send it again.

## Network

Each call makes one HTTPS GET to https://api.datacircle.dev/v1 with the tool's arguments and nothing else. The API takes up to 60 calls a minute from one address; the tools wait once, a minute at most, when it asks them to. `datacircle_toolset(timeout=10)` sets how long a call may take, and `http_client=` sends the calls through an `httpx.AsyncClient` of yours. Every plan is also one file at https://datacircle.dev/datacircle.json.

## Links

- Datacircle: https://datacircle.dev
- The API: https://datacircle.dev/api
- Its spec: https://api.datacircle.dev/v1/openapi.json
- What each key means: https://datacircle.dev/fields

MIT license.
