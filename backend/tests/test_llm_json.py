import pytest
from pydantic import BaseModel

from app.providers.fake import FakeLLM
from app.services.llm_json import LLMJSONError, ask_json, parse_json


@pytest.mark.parametrize("raw", [
    '{"a": 1, "b": [1, 2]}',
    '```json\n{"a": 1, "b": [1, 2]}\n```',
    'Sure! Here is the post:\n{"a": 1, "b": [1, 2]}\nHope you like it.',
    '{"a": 1, "b": [1, 2,],}',
    "{'a': 1, 'b': [1, 2]}",
    '{“a”: 1, “b”: [1, 2]}',
    '{"a": 1, // count\n "b": [1, 2]}',
])
def test_parse_variants(raw):
    assert parse_json(raw) == {"a": 1, "b": [1, 2]}


def test_braces_inside_strings():
    assert parse_json('noise {"caption": "a {curly} day } ok", "n": 2} tail') == {"caption": "a {curly} day } ok", "n": 2}


@pytest.mark.parametrize("raw", ["", "   ", "I can't help with that.", '{"a": 1', "[1, 2, 3]", '{"a": }'])
def test_parse_garbage(raw):
    with pytest.raises(LLMJSONError):
        parse_json(raw)


class M(BaseModel):
    title: str
    n: int


async def test_ask_json_retries_with_feedback():
    llm = FakeLLM()
    llm.queue["t"] += ['{"title": "x"', '{"title": "x", "n": "not a number"}', '{"title": "ok", "n": 3}']
    usages = []
    res = await ask_json(llm, "t", "sys", [{"type": "text", "text": "go"}], M, usages.append, retries=2)
    assert res == M(title="ok", n=3)
    assert len(usages) == 3  # failed attempts are paid for too
    assert "could not be used" in llm.calls[1][1]


async def test_ask_json_gives_up():
    llm = FakeLLM()
    llm.queue["t"] += ["nope", "still nope"]
    with pytest.raises(LLMJSONError):
        await ask_json(llm, "t", "sys", [{"type": "text", "text": "go"}], M, lambda u: None)
