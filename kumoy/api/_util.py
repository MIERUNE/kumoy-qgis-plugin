from typing import Any, Dict

# Marks an argument the caller did not pass, so that None can mean "clear"
UNSET: Any = object()


def compact(**fields: Any) -> Dict[str, Any]:
    """Drop UNSET values: PUT endpoints treat absent keys as "keep"."""
    return {k: v for k, v in fields.items() if v is not UNSET}
