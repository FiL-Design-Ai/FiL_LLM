from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple


CLEANUP_PATTERNS: List[Tuple[str, str]] = [
    (r"^(Here is|Here's|This is|The image shows|I see|Looking at|Certainly|Sure|Okay|Alright|I understand)[^.:]*[.:]?\s*", ""),
    (r"^(Based on the image|In this image|The picture shows)[^.:]*[.:]?\s*", ""),
    (r"^(The scene|This scene|The frame|This frame|The shot|The photo|The photograph|The artwork|This artwork)\s+(shows|depicts|captures|presents|features)\s*", ""),
    (r"^(I can see|It looks like|It appears that|What I notice)[^.:]*[.:]?\s*", ""),
    (r"^(Let me|Allow me|I'll|I will)[^.:]*[.:]?\s*", ""),
    (r"(^|\n)(In summary|Overall|To conclude|Final thoughts):?\s*.*$", ""),
    (r"""^\s*["'«»„"]|["'«»„"]\s*$""", ""),
    (r"\b(hints at|as if|seems to|appears to|suggests|implies|gives the impression|possibly|perhaps|might be|could be|probably|likely|somewhat|almost)\b", ""),
    (r"\b(there is a sense of|creates a sense of|conveys a sense of)\b", ""),
    (r"\b(seems|appears)\b\s+(heavy|light|made|constructed|composed|formed|like|that|to)", ""),
    (r"\b(beautiful|stunning|gorgeous|breathtaking|magnificent|exquisite)\b", ""),
    (r"```[\w-]*\n?", ""),
    (r"^(assistant|role|response|output|result|description|analysis|step \d+):\s*", ""),
    (r"\b(kinetic apex|motion vector|energy vector|maximum tension|soul[- ]?crushing beauty|pure cinematic energy)\b", ""),
    (r"<analysis_scratchpad>.*?</analysis_scratchpad>", ""),
    (r"</?analysis_scratchpad[^>]*>", ""),
    # The Russian half. Everything above only ever matched English, so a model
    # answering in the language the system prompt asks for kept its preamble:
    # `qwq-32b` opened with "Хорошо, мне нужно обработать запрос пользователя"
    # — reasoning out loud without the <think> tags that would have hidden it.
    (r"^\s*(Хорошо|Ладно|Итак|Окей|Конечно|Отлично)[,!.]?\s+(мне\s+нужно|нужно|я\s|сначала|давайте|пользовател)[^\n]*\n+", ""),
    # "Вот несколько вариантов промптов:" — a wrapper around the answer, not
    # the answer. Narrowed to the meta nouns so a real line that starts with
    # "Вот" survives.
    (r"^\s*(Вот|Ниже)\s+(?:несколько\s+|мой\s+|краткое\s+)?(вариант|промпт|описани|запрос)[^\n]*:\s*", ""),
    (r"^(Описание|Промпт|Запрос|Описание изображения|Финальный промпт)\s*:\s*", ""),
    # Explicit prompt label prefixes from reasoning models
    (r"^\s*(?:\*\*|#+)?\s*(?:Prompt|Final Prompt|Image Prompt|Positive Prompt|Generated Prompt)(?:\*\*|#+)?\s*:\s*", ""),
]

THINKING_TAGS = ("think", "thought", "reasoning", "analysis_scratchpad", "antml:thought", "plan")


def strip_thinking(text: str) -> str:
    """Safely remove thinking/reasoning blocks (both closed and unclosed tags, plus untagged preambles)."""
    if not text:
        return ""

    tag_pattern = "|".join(re.escape(t) for t in THINKING_TAGS)

    # 1. Closed thinking tags: <think>...</think>
    text = re.sub(rf"<({tag_pattern})[^>]*>.*?</\1>", "", text, flags=re.DOTALL | re.IGNORECASE)

    # 2. Unclosed thinking tags (e.g. DeepSeek-R1 ran out of tokens before closing the tag)
    unclosed_match = re.search(rf"<({tag_pattern})[^>]*>", text, flags=re.IGNORECASE)
    if unclosed_match:
        tag_start = unclosed_match.start()
        after_tag = text[unclosed_match.end():]
        # Check if the model transitioned into the prompt despite not closing the tag
        prompt_transition = re.search(
            r"(?:(?:\*\*|#+)?\s*(?:Final\s+)?Prompt\s*(?:\*\*|#+)?:|\n```(?:\w+)?\n?)\s*(.+)",
            after_tag,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if prompt_transition:
            text = text[:tag_start] + " " + prompt_transition.group(1)
        else:
            # Entire remaining text was thinking cut off mid-thought
            text = text[:tag_start]

    # Clean any dangling tags
    text = re.sub(rf"</?({tag_pattern})[^>]*>", "", text, flags=re.IGNORECASE)

    # 3. Untagged thinking blocks: "Thinking Process:\n...", "Thought:\n..."
    text = re.sub(
        r"(?is)^\s*(?:\*\*|#+)?\s*(?:Thinking|Thought|Reasoning|Analysis)(?:\s+Process)?(?:\*\*|#+)?:?\s*.*?(?=(?:\*\*|#+)?\s*(?:Final\s+)?Prompt(?:\*\*|#+)?:|\n\n+[A-ZА-Я]|\Z)",
        "",
        text,
    )

    # 4. English conversational reasoning preambles: "Okay, I need to create...", "Let's think about..."
    text = re.sub(
        r"(?is)^\s*(?:Okay|Alright|Well|Sure),?\s+(?:I need to|let's|I should|I'll|let me|we need to|the user wants)\s+[^\n]*\n+",
        "",
        text,
    )

    return text


@dataclass
class OutputCleanConfig:
    strip_think: bool = True
    strip_code_fences: bool = True
    strip_role_prefixes: bool = True
    # The final pass keeps only ASCII + Cyrillic; CJK output (Prompt Director's
    # zh language mode) must opt out or every ideograph gets deleted.
    strip_non_latin: bool = True


def clean_output(text: str, config: Optional[OutputCleanConfig] = None) -> str:
    if not text:
        return ""
    cfg = config or OutputCleanConfig()
    cleaned = text.strip()

    # Strip internal thinking first so downstream pattern cleaners operate on pure prompt text
    if cfg.strip_think:
        cleaned = strip_thinking(cleaned)
    else:
        # analysis_scratchpad is always stripped regardless of strip_think
        cleaned = re.sub(r"<analysis_scratchpad[^>]*>.*?</analysis_scratchpad>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"</?analysis_scratchpad[^>]*>", "", cleaned, flags=re.IGNORECASE)

    for pattern, replacement in CLEANUP_PATTERNS:
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE | re.MULTILINE)

    if cfg.strip_code_fences:
        cleaned = cleaned.replace("```", "")

    if cfg.strip_role_prefixes:
        cleaned = re.sub(r"^[A-Z\s]{5,25}:\s*", "", cleaned, flags=re.MULTILINE)

    cleaned = cleaned.replace("**", "").replace("__", "").replace("#", "").replace("* ", "")
    if cfg.strip_non_latin:
        cleaned = re.sub(r"[^\x00-\x7F\u0400-\u04FF\s.,!?;:\"\'()-]+", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"\s+([.,!?;:])", r"\1", cleaned)

    return cleaned.strip()
