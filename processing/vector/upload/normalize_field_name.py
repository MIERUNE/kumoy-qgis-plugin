from typing import List

MAX_FIELD_LENGTH = 63


def truncate_utf16(text: str, max_length: int) -> str:
    """Cut `text` to `max_length` UTF-16 code units.

    The server checks lengths with JavaScript's String.length, which counts
    characters outside the BMP (emoji, rare kanji) twice.
    """
    if len(text) * 2 <= max_length:
        return text  # fast path: fits even if every character were a pair
    encoded = text.encode("utf-16-le")
    if len(encoded) <= max_length * 2:
        return text
    # "ignore" drops a surrogate pair cut in half
    return encoded[: max_length * 2].decode("utf-16-le", errors="ignore")


def normalize_field_name(name: str, current_names: List[str]) -> str:
    """Make a column name the server accepts and that is not taken yet.

    - Strip leading and trailing whitespace
    - Replace line breaks with underscores
    - Cut to the maximum length
    - Add a numeric suffix when the result is already taken
    """
    normalized = name.strip()
    # Windows line breaks first, so they become one underscore
    for line_break in ("\r\n", "\n", "\r"):
        normalized = normalized.replace(line_break, "_")
    normalized = truncate_utf16(normalized, MAX_FIELD_LENGTH)

    if normalized not in current_names:
        return normalized

    # e.g. with a limit of 10, "field12345" taken -> "field123_1", ...
    # "field12_10": the base is cut further so the suffix fits
    suffix_num = 1
    while True:
        suffix = f"_{suffix_num}"
        base = truncate_utf16(normalized, MAX_FIELD_LENGTH - len(suffix))
        new_name = f"{base}{suffix}"
        if new_name not in current_names:
            return new_name
        suffix_num += 1
