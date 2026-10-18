"""Test-only scripted wire provider; production graph/SDK/egress remain real."""

import json
import re

import httpx


def scripted_completion(request: httpx.Request) -> httpx.Response:
    assert request.url.host in {"localhost", "127.0.0.1"}
    assert request.url.path == "/v1/chat/completions"
    data = json.loads(request.content)
    assert data["model"] == "qwen3.5:9b"
    messages = data["messages"]
    tools = {tool["function"]["name"] for tool in data.get("tools", [])}
    observed = [m for m in messages if m["role"] == "tool"]
    text = "\n".join(str(m.get("content", "")) for m in messages)
    user = next(m["content"] for m in reversed(messages) if m["role"] == "user")
    prior_requests = re.findall(
        r"USER PROVIDED:\n(.*?)\n\nPRIOR AGENT RESPONSE", text, re.DOTALL
    )
    scope = user
    if not re.search(r"\b(?:S\d{2}|P\d{4}|[A-Z]+-\d+)\b", scope) and prior_requests:
        scope = prior_requests[-1]
    tool_call = None
    if not observed and not data.get("response_format"):
        station = re.search(r"\bS\d{2}\b", scope)
        product = re.search(r"\bP\d{4}\b", scope)
        fault = re.search(r"\b[A-Z]+-\d+\b", scope)
        if station:
            name, arguments = "get_machine_status", {"station_id": station[0]}
            if name not in tools:
                name = "get_station_overview"
        elif product:
            name, arguments = "get_product_history", {"product_id": product[0]}
        elif fault:
            name, arguments = "search_documentation", {"query": fault[0], "top_k": 3}
        else:
            raise AssertionError("No scripted release trajectory for this request")
        assert name in tools, (name, sorted(tools))
        tool_call = (name, arguments)
    elif (
        "search_documentation" in tools
        and "QUALITY-09" in text
        and not any('"results"' in (m.get("content") or "") for m in observed)
    ):
        tool_call = ("search_documentation", {"query": "S04 QUALITY-09", "top_k": 3})
    german = any(
        marker in text
        for marker in (
            "response_language=DE",
            "response language: DE",
            "German",
            "Deutsch",
        )
    )
    evidence = "\n".join(m.get("content") or "" for m in observed) if observed else user
    identifiers = sorted(set(re.findall(r"\b(?:S\d{2}|P\d{4}|[A-Z]+-\d+)\b", evidence)))
    answer = (
        (
            "Die autorisierten Beobachtungen wurden geprüft. Die dokumentierten Ergebnisse sind: "
            if german
            else "The authorized observations were checked. The documented results are: "
        )
        + ", ".join(identifiers)
        + "."
    )
    message = {"role": "assistant", "content": answer}
    if tool_call and not data.get("response_format"):
        name, arguments = tool_call
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "scripted-" + str(len(observed)),
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)},
                }
            ],
        }
    elif data.get("response_format"):
        message["content"] = json.dumps(
            {
                "answer": answer,
                "next_steps": [],
                "investigation_steps": [],
                "identifiers": [],
                "documents": [],
            }
        )
    return httpx.Response(
        200,
        json={
            "id": "test-only-scripted",
            "object": "chat.completion",
            "created": 1,
            "model": data["model"],
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": "tool_calls"
                    if message.get("tool_calls")
                    else "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    )
