import re


DEFAULT_ORDER_YEAR = "2024"

_DIGIT_WORDS = {
    "zero": "0", "oh": "0",
    "one": "1", "won": "1",
    "two": "2", "to": "2", "too": "2",
    "three": "3", "tree": "3",
    "four": "4", "for": "4",
    "five": "5", "six": "6", "seven": "7",
    "eight": "8", "ate": "8", "nine": "9",
}
_FILLERS = {"order", "ord", "id", "number", "is", "the", "my"}


def canonical_order_id(value: str) -> str | None:
    """Return ORD-YYYY-NNNN for a full ID or a unique four-digit suffix."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 4:
        return f"ORD-{DEFAULT_ORDER_YEAR}-{digits}"
    if len(digits) == 8:
        return f"ORD-{digits[:4]}-{digits[4:]}"
    return None


def _spoken_digits(text: str) -> str:
    # Speech engines often render "2024" as "twenty twenty four".
    text = re.sub(r"\btwenty[\s-]+twenty[\s-]+four\b", "2024", text.lower())
    tokens = re.findall(r"[a-z]+|\d+", text)
    output: list[str] = []
    repeat = 1

    for token in tokens:
        if token in _FILLERS:
            continue
        if token == "double":
            repeat = 2
            continue
        if token == "triple":
            repeat = 3
            continue
        digit = token if token.isdigit() else _DIGIT_WORDS.get(token)
        if digit is None:
            # A non-number word means this is not a standalone spoken ID.
            return ""
        output.append(digit * repeat)
        repeat = 1

    return "".join(output)


def normalize_order_mentions(text: str) -> str:
    """Append a canonical hint for typed or speech-recognized order numbers.

    Examples: "5544", "order five five four four", "order 2024 5544".
    The original transcript is retained for auditability.
    """
    if not text or re.search(r"\bORD-\d{4}-\d{4}\b", text, re.IGNORECASE):
        return text

    canonical = None
    marker = re.search(r"\b(?:order(?:\s+(?:id|number))?|ord)\b", text, re.IGNORECASE)
    if marker:
        candidate = text[marker.start():]
        # Prefer explicit numeric forms, including "order 2024 5544".
        numeric = re.search(r"(?<!\d)(\d{4})[\s-]+(\d{4})(?!\d)", candidate)
        if numeric:
            canonical = f"ORD-{numeric.group(1)}-{numeric.group(2)}"
        else:
            suffix = re.search(r"(?<!\d)(\d{4})(?!\d)", candidate)
            if suffix:
                canonical = canonical_order_id(suffix.group(1))
            else:
                canonical = canonical_order_id(_spoken_digits(candidate))
    else:
        stripped = text.strip()
        if re.fullmatch(r"\d{4}|\d{8}|\d{4}[\s-]\d{4}", stripped):
            canonical = canonical_order_id(stripped)
        else:
            canonical = canonical_order_id(_spoken_digits(stripped))

    if not canonical:
        return text
    return f"{text}\n[Normalized order ID: {canonical}]"
