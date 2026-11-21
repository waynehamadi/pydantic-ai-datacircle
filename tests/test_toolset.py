"""The toolset with no network: what each tool sends to the API, what a model reads of each, and how answers and refusals reach it
through an agent's run."""

import asyncio
import json

import httpx
import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, RetryPromptPart, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.toolsets import FunctionToolset

from pydantic_ai_datacircle import Datacircle, _api, datacircle_toolset

NAMES = ["datacircle_list_apis", "datacircle_best_plans", "datacircle_search_plans", "datacircle_provider"]
PLAN = {"rank": 1, "provider": "Emelia", "plan": "Starter", "score": 91.2, "perThousand": 4.99, "page": "https://datacircle.dev/p",
        "use": "a long terms of use", "aggregators": [], "waterfall": None}


@pytest.fixture
def api(monkeypatch):
    """An httpx client answering from a dict of path to (status, body), each request kept."""
    sent, answers = [], {}

    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split("/v1", 1)[1]
        sent.append((path, dict(request.url.params), request.headers.get("user-agent")))
        status, body = answers[path].pop(0) if isinstance(answers[path], list) else answers[path]
        return httpx.Response(status, json=body, headers={"Retry-After": "1"})

    async def no_wait(seconds):
        return None

    monkeypatch.setattr(_api.asyncio, "sleep", no_wait)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    return sent, answers, client


def retried(part) -> bool:
    """A call sent back to the model to fix: a RetryPromptPart before Pydantic AI 2, a ToolReturnPart retried since."""
    return isinstance(part, RetryPromptPart) or getattr(part, "outcome", None) == "retried"


def run(toolset, *calls, retries=None):
    """An agent's run on a scripted model that asks for calls (name, arguments) at once, then for each the model sent
    again after a retry, then ends: the parts the tools gave back, in order."""
    def model(messages, info):
        last = messages[-1].parts
        again = [part for part in last if retried(part)]
        if len(messages) == 1:
            return ModelResponse(parts=[ToolCallPart(name, args, f"call_{i}") for i, (name, args) in enumerate(calls)])
        if again and retries:
            return ModelResponse(parts=[ToolCallPart(part.tool_name, retries.pop(0), "call_again") for part in again])
        return ModelResponse(parts=[TextPart("done")])

    agent = Agent(FunctionModel(model), toolsets=[toolset])
    result = agent.run_sync("Which email finder is best?")
    assert result.output == "done"
    return [part for message in result.all_messages() for part in getattr(message, "parts", [])
            if isinstance(part, (ToolReturnPart, RetryPromptPart))]


def test_the_four_tools_as_a_model_reads_them():
    toolset = datacircle_toolset()
    assert isinstance(toolset, FunctionToolset) and list(toolset.tools) == NAMES and toolset.id == "datacircle"
    definitions = {name: tool.tool_def if hasattr(tool, "tool_def") else tool for name, tool in toolset.tools.items()}
    assert all("https://datacircle.dev" in definition.description for definition in definitions.values())
    assert all(prop.get("description") for definition in definitions.values()
               for prop in definition.parameters_json_schema["properties"].values())
    schema = definitions["datacircle_search_plans"].parameters_json_schema
    assert list(schema["properties"]) == ["api", "query", "sort", "limit", "offset"] and not schema.get("required")
    assert schema["properties"]["sort"]["anyOf"][0]["enum"] == ["score", "provider", "price"]
    assert definitions["datacircle_best_plans"].parameters_json_schema["required"] == ["slug"]
    assert list(datacircle_toolset(include=["provider", "datacircle_best_plans"]).tools) == NAMES[1:4:2]
    with pytest.raises(ValueError, match="list_apis, best_plans"):
        datacircle_toolset(include=["plans"])


def test_each_tool_sends_its_call_and_gives_the_answer_cut(api):
    sent, answers, client = api
    answers["/apis"] = (200, [{"api": "Employee email", "slug": "email-finder", "plans": 40, "providers": 12, "extra": 1},
                              {"api": "Phone finder", "slug": "phone-finder", "plans": 9, "providers": 4}])
    answers["/apis/email-finder/best"] = (200, {"api": "Employee email", "slug": "email-finder", "total": 50, "plans": [PLAN]})
    answers["/plans"] = (200, {"total": 1, "offset": 0, "plans": [PLAN]})
    answers["/providers/bright-data"] = (200, {"provider": "Bright Data", "apis": [
        {"api": "LinkedIn profile", "slug": "linkedin-profile", "rank": 3, "plans": [{**PLAN, "rank": 9}, {**PLAN, "rank": 3, "plan": "Pro"}]}]})
    parts = run(datacircle_toolset(http_client=client),
                ("datacircle_list_apis", {"query": "phone"}),
                ("datacircle_best_plans", {"slug": "Email Finder", "limit": 3}),
                ("datacircle_search_plans", {"api": "email-finder", "query": "emelia", "sort": "price", "limit": "2"}),
                ("datacircle_provider", {"slug": "Bright Data"}))
    returned = {part.tool_name: part.content for part in parts}
    assert [part.tool_name for part in parts] == NAMES and not any(retried(part) for part in parts)
    assert returned["datacircle_list_apis"] == {"total": 1, "apis": [{"api": "Phone finder", "slug": "phone-finder", "plans": 9, "providers": 4}]}
    assert returned["datacircle_best_plans"]["plans"] == [{key: PLAN[key] for key in ("rank", "provider", "plan", "score", "perThousand", "page")}]
    assert returned["datacircle_search_plans"]["total"] == 1
    assert returned["datacircle_provider"]["apis"] == [{"api": "LinkedIn profile", "slug": "linkedin-profile", "rank": 3, "plans": 2,
                                                         "best": {"plan": "Pro", "score": 91.2, "perThousand": 4.99, "page": "https://datacircle.dev/p"}}]
    assert sorted(sent[:4]) == sorted([
        ("/apis", {}, "pydantic-ai-datacircle/0.1.0"),
        ("/apis/email-finder/best", {"limit": "3"}, "pydantic-ai-datacircle/0.1.0"),
        ("/plans", {"api": "email-finder", "query": "emelia", "sort": "price", "limit": "2"}, "pydantic-ai-datacircle/0.1.0"),
        ("/providers/bright-data", {}, "pydantic-ai-datacircle/0.1.0")])
    assert json.loads(json.dumps(returned))  # what the model reads is JSON


def test_a_refusal_reaches_the_model_as_its_words(api):
    sent, answers, client = api
    answers["/apis/nope/best"] = (404, {"error": "no API has the slug nope", "slugs": ["email-finder", "phone-finder"]})
    answers["/providers/x"] = (404, {"error": "no provider has the slug x"})
    parts = run(datacircle_toolset(http_client=client), ("datacircle_best_plans", {"slug": "nope"}),
                ("datacircle_provider", {"slug": "x"}), ("datacircle_best_plans", {"slug": " - "}))
    assert [part.content for part in parts] == [
        {"error": "Datacircle's API answered 404: no API has the slug nope; the slugs: email-finder, phone-finder"},
        {"error": "Datacircle's API answered 404: no provider has the slug x"},
        {"error": "Give an API's slug, like 'email-finder': datacircle_list_apis gives every slug"}]
    assert len(sent) == 2


def test_an_argument_out_of_range_is_sent_back_before_any_call(api):
    sent, answers, client = api
    answers["/apis/email-finder/best"] = (200, {"plans": [PLAN]})
    parts = run(datacircle_toolset(http_client=client), ("datacircle_best_plans", {"slug": "email-finder", "limit": 99}),
                retries=[{"slug": "email-finder", "limit": 5}])
    assert retried(parts[0]) and "50" in json.dumps(parts[0].content, default=str)
    assert not retried(parts[1]) and parts[1].content["plans"][0]["provider"] == "Emelia"
    assert sent == [("/apis/email-finder/best", {"limit": "5"}, "pydantic-ai-datacircle/0.1.0")]


def test_a_429_is_waited_once_then_given(api):
    sent, answers, client = api
    answers["/apis"] = [(429, {"error": "slow down"}), (200, [{"api": "A", "slug": "a"}])]
    assert asyncio.run(Datacircle(http_client=client).list_apis()) == {"total": 1, "apis": [{"api": "A", "slug": "a"}]}
    answers["/apis"] = [(429, {}), (429, {})]
    assert "429 twice" in asyncio.run(Datacircle(http_client=client).list_apis())["error"]


def test_an_api_out_of_reach_is_an_answer_not_a_crash():
    def handle(request):
        raise httpx.ConnectError("refused", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    (part,) = run(datacircle_toolset(http_client=client), ("datacircle_list_apis", {}))
    assert part.content["error"].startswith("Datacircle's API could not be reached")
