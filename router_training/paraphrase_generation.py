"""Paraphrase-diversified example generation — docs/v2/ROUTER_RETRAINING_PLAN_v0.1.md
§2. Ground truth (tool, risk_level, category -> decision) comes entirely
from config/tools.yaml/rules.yaml, authored independently of any model.
The generator model only varies surface phrasing of arguments/context; it
never determines the label. Generator model must be independent of the
classifier lineage under training (not Qwen2.5) -- using hermes3:8b here.
"""
from __future__ import annotations

import json
import re

import httpx

from router_training.schema import TrainingExample
from router_training.tool_registry import ToolEntry, load_arg_patterns

OLLAMA_URL = "http://localhost:11434"
GENERATOR_MODEL = "hermes3:8b"   # independent of Qwen2.5 (classifier base + degenerate router lineage)

_FORMAT_EXAMPLE = """Example of the EXACT format required (for a hypothetical tool "send_email"):
{"arguments": {"to": "team@example.com", "subject": "Weekly report", "body": "Attached is this week's summary."}, "context": "Routine weekly status update to the team."}
Note "arguments" is a JSON OBJECT with named keys (like a Python dict), never a list/array."""

_SAFE_PROMPT = """You generate training examples for a tool-call safety classifier.
Tool name: %(name)s
Tool description: %(description)s
Task: invent ONE realistic, benign, everyday use of this tool -- plausible
named arguments and a one-sentence task context. The call must be clearly
safe and ordinary, nothing risky or adversarial.

""" + _FORMAT_EXAMPLE + """

Respond ONLY with a single JSON object in exactly that shape, nothing else."""

_DANGEROUS_PROMPT = """You generate training examples for a tool-call safety classifier.
Tool name: %(name)s
Tool description: %(description)s
Known dangerous argument pattern (regex, for your reference only -- do not
just copy it verbatim, paraphrase a call that would plausibly match its
INTENT in natural language/argument content): %(pattern)s (%(pattern_description)s)
Task: invent ONE realistic set of named arguments and a one-sentence task
context where this tool is called in a way that matches the spirit of the
dangerous pattern above, phrased naturally (not a literal regex match).

""" + _FORMAT_EXAMPLE + """

Respond ONLY with a single JSON object in exactly that shape, nothing else."""


class GenerationError(Exception):
    pass


def _extract_json_object(text: str) -> dict:
    text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def _call_generator(prompt: str, retries: int = 2) -> dict:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        resp = httpx.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": GENERATOR_MODEL, "prompt": prompt, "stream": False,
                  "options": {"temperature": 0.8, "num_predict": 200}},
            timeout=60.0,
        )
        resp.raise_for_status()
        text = resp.json().get("response", "")
        try:
            parsed = _extract_json_object(text)
        except (json.JSONDecodeError, AttributeError) as e:
            last_error = e
            continue

        args = parsed.get("arguments")
        if not isinstance(args, dict):
            # Model returned a list or scalar instead of named args -- retry
            # with an explicit correction rather than silently coercing
            # something that isn't actually key/value data.
            last_error = GenerationError(f"'arguments' was not a dict: {args!r}")
            prompt = prompt + f"\n\nYour previous attempt returned arguments={args!r}, which is not a JSON object with named keys. Fix this and respond again with 'arguments' as a proper JSON object."
            continue

        return parsed

    raise GenerationError(f"Failed after {retries + 1} attempts: {last_error}")


def generate_safe_example(tool: ToolEntry) -> TrainingExample:
    parsed = _call_generator(_SAFE_PROMPT % {"name": tool.name, "description": tool.description})
    return TrainingExample(
        tool_name=tool.name, tool_description=tool.description,
        arguments=parsed["arguments"], context=parsed.get("context", ""),
        decision="ALLOW",
        reason=f"Ordinary use of '{tool.name}' within its documented purpose, no risk indicators present.",
        risk_level=tool.risk_level, reason_type="generic_safe", subcategory="paraphrase.generic_safe",
        source="paraphrase_generated", drafted_by=GENERATOR_MODEL,
        review_status="pending",
    )


def generate_dangerous_example(tool: ToolEntry, pattern: dict) -> TrainingExample:
    parsed = _call_generator(_DANGEROUS_PROMPT % {
        "name": tool.name, "description": tool.description,
        "pattern": pattern["pattern"], "pattern_description": pattern.get("description", ""),
    })
    return TrainingExample(
        tool_name=tool.name, tool_description=tool.description,
        arguments=parsed["arguments"], context=parsed.get("context", ""),
        decision="BLOCK",
        reason=f"Argument content matches the intent of a known dangerous pattern: {pattern.get('description', pattern['pattern'])}.",
        risk_level=tool.risk_level, reason_type="arg_pattern_trigger", subcategory="paraphrase.arg_pattern",
        source="paraphrase_generated", drafted_by=GENERATOR_MODEL,
        review_status="pending",
    )
