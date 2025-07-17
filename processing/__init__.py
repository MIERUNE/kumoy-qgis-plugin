"""
STRATO Processing provider
"""

# Only import FieldNameNormalizer for testing purposes
# Avoid importing provider to prevent dependency issues in tests
try:
    from .provider import StratoProcessingProvider

    __all__ = ["StratoProcessingProvider", "FieldNameNormalizer"]
except ImportError:
    # In test environment, only expose FieldNameNormalizer
    __all__ = ["FieldNameNormalizer"]

from .field_name_normalizer import FieldNameNormalizer
