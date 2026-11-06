"""Getting JSON out of an LLM answer, even when it's wrapped in prose or code fences or slightly broken."""

from __future__ import annotations

import ast
import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from ..providers.base import LLM, Usage

T = TypeVar("T", bound=BaseModel)


class LLMJSONError(Exception):
    pass


def _outer_object(text: str) -> str | None:
    """The first balanced {...} in `text`, ignoring braces inside strings."""
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
        start = text.find("{", start + 1)
    return None


def _repairs(s: str):
    yield s
    s2 = re.sub(r",\s*([}\]])", r"\1", s)  # trailing commas
    yield s2
    s3 = s2.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    yield s3
    s4 = re.sub(r"//[^\n\"]*$", "", s3, flags=re.M)  # line comments outside strings (best effort)
    yield s4


def parse_json(text: str) -> dict:
    if not text or not text.strip():
        raise LLMJSONError("empty answer")
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if fence:
        t = fence.group(1).strip()
    candidates = [t]
    obj = _outer_object(t)
    if obj and obj != t:
        candidates.append(obj)
    for cand in candidates:
        for fixed in _repairs(cand):
            try:
                data = json.loads(fixed)
            except json.JSONDecodeError:
                pass
            else:
                if isinstance(data, dict):
                    return data
            try:  # single quotes, True/False/None
                py = re.sub(r"\btrue\b", "True", re.sub(r"\bfalse\b", "False", re.sub(r"\bnull\b", "None", fixed)))
                data = ast.literal_eval(py)
            except (ValueError, SyntaxError, MemoryError, RecursionError):
                continue
            if isinstance(data, dict):
                return data
    raise LLMJSONError("no JSON object in the answer")


async def ask_json(llm: LLM, task: str, system: str, content: list[dict], model: type[T],
                   on_usage, retries: int = 1, max_tokens: int = 4000) -> T:
    """Call the LLM and validate its JSON against `model`. On a bad answer, ask again once, telling the model
    what was wrong. Every call's usage goes to `on_usage` (also the failed ones: they cost money too)."""
    last_err = ""
    msgs = list(content)
    for attempt in range(retries + 1):
        res = await llm.complete(task, system, msgs, max_tokens=max_tokens)
        on_usage(res.usage)
        try:
            return model.model_validate(parse_json(res.text))
        except (LLMJSONError, ValidationError) as e:
            last_err = str(e)[:600]
        if attempt < retries:
            msgs = list(content) + [{"type": "text", "text": (
                "Your previous answer could not be used: " + last_err +
                "\nAnswer again with a single JSON object that follows the schema exactly, and nothing else.")}]
    raise LLMJSONError(f"{task}: {last_err}")


def usage_sink(items: list[Usage]):
    return items.append
