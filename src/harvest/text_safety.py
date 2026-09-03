from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


REPLACEMENT_CHARACTER = "�"


def sanitize_untrusted_text(value: str) -> str:
    """Keep terminal-safe printable text and normalized newlines only."""
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return "".join(
        character
        if character == "\n" or character.isprintable()
        else REPLACEMENT_CHARACTER
        for character in normalized
    )


def sanitize_untrusted_data(value: Any) -> Any:
    """Recursively sanitize strings received from users, files, or providers."""
    if isinstance(value, str):
        return sanitize_untrusted_text(value)
    if isinstance(value, Mapping):
        return {
            sanitize_untrusted_text(key) if isinstance(key, str) else key: sanitize_untrusted_data(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_untrusted_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_untrusted_data(item) for item in value)
    return value


def escape_markdown_text(value: str) -> str:
    """Escape Markdown syntax in data while keeping normal prose readable."""
    safe = sanitize_untrusted_text(value)
    safe = safe.replace("\\", "\\\\")
    for character in ("`", "*", "_", "[", "]", "<", ">", "|", "&"):
        safe = safe.replace(character, f"\\{character}")

    def escape_line(line: str) -> str:
        leading_spaces = len(line) - len(line.lstrip(" "))
        prefix = "\N{NO-BREAK SPACE}" * leading_spaces
        content = line[leading_spaces:]
        content = re.sub(r"^(#{1,6}|[+-](?=\s)|~{3,}|\d+[.)](?=\s))", r"\\\1", content)
        if re.fullmatch(r"[=-]{2,}\s*", content):
            content = "\\" + content
        return prefix + content

    return "\n".join(escape_line(line) for line in safe.split("\n"))
