import re

MAX_FIELD_LENGTH = 63

RESERVED_KEYWORDS = {
    "all",
    "analyse",
    "analyze",
    "and",
    "any",
    "array",
    "as",
    "asc",
    "asymmetric",
    "authorization",
    "binary",
    "both",
    "case",
    "cast",
    "check",
    "collate",
    "collation",
    "column",
    "concurrently",
    "constraint",
    "create",
    "cross",
    "current_catalog",
    "current_date",
    "current_role",
    "current_schema",
    "current_time",
    "current_timestamp",
    "current_user",
    "default",
    "deferrable",
    "desc",
    "distinct",
    "do",
    "else",
    "end",
    "except",
    "false",
    "fetch",
    "for",
    "foreign",
    "freeze",
    "from",
    "full",
    "grant",
    "group",
    "having",
    "ilike",
    "in",
    "initially",
    "inner",
    "intersect",
    "into",
    "is",
    "isnull",
    "join",
    "lateral",
    "leading",
    "left",
    "like",
    "limit",
    "localtime",
    "localtimestamp",
    "natural",
    "not",
    "notnull",
    "null",
    "offset",
    "on",
    "only",
    "or",
    "order",
    "outer",
    "overlaps",
    "placing",
    "primary",
    "references",
    "returning",
    "right",
    "select",
    "session_user",
    "similar",
    "some",
    "symmetric",
    "system_user",
    "table",
    "tablesample",
    "then",
    "to",
    "trailing",
    "true",
    "union",
    "unique",
    "user",
    "using",
    "variadic",
    "verbose",
    "when",
    "where",
    "window",
    "with",
}


def normalize_field_name(name: str, current_names: list[str]) -> str:
    """Normalize field name for PostgreSQL/PostGIS compatibility"""
    # Convert to lowercase
    # Example: "Field Name" → "field name", "SELECT" → "select"
    normalized = name.lower()

    # Replace spaces, hyphens, and other common separators with underscores
    # Example: "field name" → "field_name", "my-field!" → "my_field_", "field.with.dots" → "field_with_dots"
    normalized = re.sub(r"[\s\-\.\,\;\:\!\?\(\)\[\]\{\}]+", "_", normalized)

    # Remove all characters that are not alphanumeric or underscore
    # Example: "my_field_" → "my_field", "データ項目" → "", "field@#$" → "field"
    normalized = re.sub(r"[^a-z0-9_]", "", normalized)

    # Remove leading digits
    # Example: "123_field" → "_field", "456" → ""
    normalized = re.sub(r"^[0-9]+", "", normalized)

    if normalized and normalized[0].isdigit():
        # If the name starts with a digit after cleaning, prepend 'field_'
        # Example: "_field" → "field__field", "123abc" → "field_abc"
        normalized = "field_" + normalized

    # Limit length to PostgreSQL identifier limit
    # Example: "very_long_field_name_that_exceeds_postgresql_limit_of_63_chars" → "very_long_field_name_that_exceeds_postgresql_limit_of_63_ch"
    if len(normalized) > MAX_FIELD_LENGTH:
        normalized = normalized[:MAX_FIELD_LENGTH]

    # Handle reserved keywords by appending '_'
    # Example: "select" → "select_", "where" → "where_"
    if normalized in RESERVED_KEYWORDS:
        normalized = normalized + "_"
        # Recheck length
        if len(normalized) > MAX_FIELD_LENGTH:
            normalized = normalized[: MAX_FIELD_LENGTH - 1] + "_"

    # Final validation - if still invalid, use a generic name with avoiding collisions
    # Example: "" → "field", "field" (if already exists) → "field_1", "field_2", etc.
    if not normalized or not re.match(r"^[a-z_][a-z0-9_]*$", normalized):
        base_name = "field"
        suffix = 1
        normalized = base_name
        while normalized in current_names:
            normalized = f"{base_name}_{suffix}"
            suffix += 1

    return normalized
