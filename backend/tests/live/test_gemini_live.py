import json
import os

import pytest

from app.llm.gemini import GeminiBackend
from app.settings import load_env_file

pytestmark = pytest.mark.live

SCHEMA = {
    "type": "object",
    "properties": {"saluto": {"type": "string"}},
    "required": ["saluto"],
}


async def test_gemini_risponde_json_conforme_allo_schema() -> None:
    load_env_file()
    key, model = os.environ.get("GEMINI_API_KEY", "").strip(), os.environ.get("GEMINI_MODEL", "")
    if not key or not model.strip():
        pytest.skip("servono GEMINI_API_KEY e GEMINI_MODEL")
    text = await GeminiBackend(key).generate(
        model=model.strip(),
        system="Rispondi solo con JSON conforme allo schema.",
        contents='{"richiesta": "saluta in italiano, in una parola"}',
        schema=SCHEMA,
        temperature=0.0,
        timeout_s=20,
    )
    assert isinstance(json.loads(text)["saluto"], str)
