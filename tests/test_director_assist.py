from __future__ import annotations

import pytest

from FiL_Design_ImageMind.common.director_assist import (
    ASSIST_MAX_TEXT_LEN,
    ASSIST_OPERATIONS,
    build_assist_system_prompt,
    validate_assist_request,
)


def _valid_body(**overrides):
    body = {"operation": "rephrase", "text": "make it photorealistic", "provider": "ollama", "model": "qwen2.5:7b"}
    body.update(overrides)
    return body


@pytest.mark.parametrize("operation", ASSIST_OPERATIONS)
def test_system_prompt_contains_op_rules_and_common_rules(operation):
    prompt = build_assist_system_prompt(operation)
    assert "same language as the input" in prompt
    assert "Output only the rewritten instruction" in prompt


def test_system_prompts_differ_per_operation():
    prompts = {build_assist_system_prompt(op) for op in ASSIST_OPERATIONS}
    assert len(prompts) == len(ASSIST_OPERATIONS)


def test_expand_prompt_carries_the_dit_physics_not_meta_noise():
    prompt = build_assist_system_prompt("expand")
    assert "material truth" in prompt
    assert "meta-noise" in prompt


def test_unknown_operation_raises():
    with pytest.raises(ValueError):
        build_assist_system_prompt("translate")


def test_valid_body_passes():
    assert validate_assist_request(_valid_body()) is None


def test_non_dict_body_rejected():
    assert validate_assist_request(["nope"]) is not None


@pytest.mark.parametrize("operation", ["", "translate", None])
def test_unknown_operation_rejected(operation):
    assert validate_assist_request(_valid_body(operation=operation)) is not None


@pytest.mark.parametrize("text", ["", "   ", None, 42])
def test_empty_or_non_string_text_rejected(text):
    assert validate_assist_request(_valid_body(text=text)) is not None


def test_overlong_text_rejected():
    assert validate_assist_request(_valid_body(text="x" * (ASSIST_MAX_TEXT_LEN + 1))) is not None


def test_unknown_provider_rejected():
    assert validate_assist_request(_valid_body(provider="not-a-provider")) is not None


@pytest.mark.parametrize("model", ["", "(loading...)", "(no models)"])
def test_placeholder_model_rejected(model):
    assert validate_assist_request(_valid_body(model=model)) is not None


def test_prompt_context_system_prompt():
    prompt = build_assist_system_prompt("expand", context="prompt")
    assert "image generation prompt" in prompt
    assert "light behavior" in prompt
    assert "material truth" in prompt


def test_unknown_context_rejected():
    assert validate_assist_request(_valid_body(context="invalid_context")) is not None
    assert validate_assist_request(_valid_body(context="prompt")) is None
    assert validate_assist_request(_valid_body(context="instruction")) is None


@pytest.mark.parametrize("style", ["photorealism", "cinematic", "anime", "neutral"])
def test_style_system_prompt(style):
    prompt = build_assist_system_prompt("expand", context="prompt", style=style)
    assert "image generation prompt" in prompt
    if style == "photorealism":
        assert "lens optics" in prompt
    elif style == "cinematic":
        assert "cinematic film aesthetics" in prompt
    elif style == "anime":
        assert "stylized animation" in prompt


@pytest.mark.parametrize("length", ["concise", "detailed", "balanced"])
def test_length_system_prompt(length):
    prompt = build_assist_system_prompt("rephrase", context="prompt", length=length)
    if length == "concise":
        assert "concise, dense, and punchy" in prompt
    elif length == "detailed":
        assert "rich, highly descriptive" in prompt


@pytest.mark.parametrize("lang,expected", [("en", "strictly in English"), ("ru", "strictly in Russian"), ("auto", "same language")])
def test_language_system_prompt(lang, expected):
    prompt = build_assist_system_prompt("rephrase", context="prompt", target_language=lang)
    assert expected in prompt


def test_invalid_style_length_language_rejected():
    assert validate_assist_request(_valid_body(style="bad_style")) is not None
    assert validate_assist_request(_valid_body(length="super_long")) is not None
    assert validate_assist_request(_valid_body(target_language="de")) is not None
    assert validate_assist_request(_valid_body(style="photorealism", length="concise", target_language="en")) is None
    assert validate_assist_request(_valid_body(style="precise", length="targeted", target_language="ru")) is None


@pytest.mark.parametrize("style,expected", [
    ("precise", "strict, clear, and unambiguous"),
    ("creative", "rich atmospheric and artistic nuance"),
    ("minimal", "concise, punchy bullet-like"),
])
def test_instruction_tone_system_prompt(style, expected):
    prompt = build_assist_system_prompt("expand", context="instruction", style=style)
    assert "editing instruction" in prompt
    assert expected in prompt


@pytest.mark.parametrize("length,expected", [
    ("targeted", "Modify strictly the specified visual aspects"),
    ("comprehensive", "comprehensively orchestrate"),
])
def test_instruction_scope_system_prompt(length, expected):
    prompt = build_assist_system_prompt("rephrase", context="instruction", length=length)
    assert "editing instruction" in prompt
    assert expected in prompt


