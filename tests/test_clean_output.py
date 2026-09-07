from __future__ import annotations

from FiL_Design_ImageMind.common.clean_output import OutputCleanConfig, clean_output


def test_strip_think_true_removes_think_block_by_default():
    text = "<think>internal reasoning</think>a red car on a street"
    assert clean_output(text) == "a red car on a street"


def test_strip_think_false_preserves_think_block():
    text = "<think>internal reasoning</think>a red car on a street"
    result = clean_output(text, OutputCleanConfig(strip_think=False))
    assert "<think>internal reasoning</think>" in result
    assert "a red car on a street" in result


def test_analysis_scratchpad_always_stripped_regardless_of_strip_think():
    text = "<analysis_scratchpad>notes</analysis_scratchpad>a red car"
    result = clean_output(text, OutputCleanConfig(strip_think=False))
    assert "analysis_scratchpad" not in result
    assert "a red car" in result


def test_russian_reasoning_preamble_is_stripped():
    """Observed on 2026-07-29: `@cf/qwen/qwq-32b` thinks out loud in Russian.

    Nothing marks it — no <think> tags — so before this the whole planning
    paragraph shipped as the image prompt.
    """
    text = (
        "Хорошо, мне нужно обработать запрос пользователя о создании описания.\n"
        "Одинокий белый маяк на скалистом утёсе, рассветное небо."
    )
    result = clean_output(text)
    assert "мне нужно обработать" not in result
    assert result.startswith("Одинокий белый маяк")


def test_russian_wrapper_and_label_are_stripped():
    assert clean_output("Вот несколько вариантов промптов:\nмаяк на скале") == "маяк на скале"
    assert clean_output("Описание: маяк на скале") == "маяк на скале"


def test_a_real_line_starting_with_vot_survives():
    """The wrapper rule is narrowed to meta nouns on purpose."""
    assert clean_output("Вот маяк стоит на скале") == "Вот маяк стоит на скале"


def test_strip_non_latin_true_removes_cjk_by_default():
    assert clean_output("一位少女站在雨中") == ""


def test_strip_non_latin_false_preserves_cjk():
    """Prompt Director's zh output passes through with its ideographs."""
    text = "一位少女站在雨中，胶片质感"
    assert clean_output(text, OutputCleanConfig(strip_non_latin=False)) == text


def test_strip_non_latin_false_still_cleans_metadata():
    text = "<think>reasoning</think>一位少女, masterpiece"
    result = clean_output(text, OutputCleanConfig(strip_non_latin=False))
    assert "think" not in result
    assert "masterpiece" in result
    assert "一位少女" in result


def test_strip_unclosed_think_tag_cut_off():
    # Model hit token limit during internal reasoning
    text = "<think>Wait, the user wants a portrait. I should think about lighting, rim light and"
    assert clean_output(text) == ""


def test_strip_unclosed_think_tag_with_prompt_transition():
    # Model didn't close <think> but transitioned to Prompt:
    text = "<think>Let me formulate this.\nPrompt: cinematic shot of an astronaut on Mars"
    assert clean_output(text) == "cinematic shot of an astronaut on Mars"


def test_strip_thought_and_reasoning_tags():
    text = "<thought>deep thoughts</thought><reasoning>logic</reasoning>ancient fantasy castle"
    assert clean_output(text) == "ancient fantasy castle"


def test_strip_untagged_thinking_process_block():
    text = "Thinking Process:\n1. Analyze subject\n2. Add details\n\nPrompt: cybernetic tiger in neon jungle"
    assert clean_output(text) == "cybernetic tiger in neon jungle"


def test_strip_english_conversational_preamble():
    text = "Okay, I need to create a detailed prompt for the user.\nA majestic lion resting under an acacia tree"
    assert clean_output(text) == "A majestic lion resting under an acacia tree"

