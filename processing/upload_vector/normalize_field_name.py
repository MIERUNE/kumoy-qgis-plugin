import re
from typing import Dict, Literal, Optional, cast

from qgis.core import QgsField, QgsFields, QgsProcessingFeedback, QgsVectorLayer
from qgis.PyQt.QtCore import QMetaType

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


def normalize_field_name(name: str) -> str:
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

    # Final validation - if still invalid, use a generic name
    if not normalized or not re.match(r"^[a-z_][a-z0-9_]*$", normalized):
        normalized = "field"

    return normalized


class FieldNameNormalizer:
    """Normalizes field names for PostgreSQL/PostGIS compatibility and manages mappings"""

    # PostgreSQL identifier length limit
    MAX_FIELD_LENGTH = 63

    # PostgreSQL reserved keywords (common ones)
    # https://www.postgresql.org/docs/current/sql-keywords-appendix.html
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

    def __init__(
        self, layer: QgsVectorLayer, feedback: Optional[QgsProcessingFeedback] = None
    ):
        """Initialize with a layer and optional feedback"""
        self.layer = layer
        self.feedback = feedback
        self._normalized_columns: Dict[str, str] = {}
        self._field_name_mapping: Dict[str, str] = {}
        self._normalized_to_original: Dict[str, str] = {}
        self._empty_field_counter = 1  # Counter for empty field names
        self._process_fields()

    @property
    def columns(self) -> Dict[str, str]:
        """Get normalized columns with their data types"""
        return self._normalized_columns

    @property
    def field_name_mapping(self) -> Dict[str, str]:
        """Get mapping from original field names to normalized names"""
        return self._field_name_mapping

    @property
    def normalized_to_original(self) -> Dict[str, str]:
        """Get mapping from normalized field names to original names"""
        return self._normalized_to_original

    def get_normalized_fields(self) -> QgsFields:
        """Get QgsFields with normalized names for upload"""
        normalized_fields = QgsFields()

        for field in self.layer.fields():
            if field.name() in self._field_name_mapping:
                normalized_name = self._field_name_mapping[field.name()]
                if normalized_name in self._normalized_columns:
                    # Create new field with normalized name
                    new_field = QgsField(field)
                    new_field.setName(normalized_name)
                    normalized_fields.append(new_field)

        return normalized_fields

    def _process_fields(self) -> None:
        """Process all fields and create mappings"""
        tracked_skipped_fields = []
        tracked_renamed_fields = []

        for field in self.layer.fields():
            field = cast(QgsField, field)
            original_name = field.name()
            normalized_name = self._normalize_field_name(original_name)

            # Check for duplicates after normalization
            if normalized_name in self._normalized_columns:
                normalized_name = self._make_unique(normalized_name)

            # Track if name was changed
            if original_name != normalized_name:
                tracked_renamed_fields.append(f"{original_name} → {normalized_name}")

            self._field_name_mapping[original_name] = normalized_name
            self._normalized_to_original[normalized_name] = original_name

            # Map field type
            field_type = self._get_field_type(field)
            if field_type:
                self._normalized_columns[normalized_name] = field_type
            else:
                # Skip unsupported field types
                # https://doc.qt.io/qt-6/qmetatype.html#Type-enum
                type_name = (
                    QMetaType.typeName(field.type()) if field.type() > 0 else "Unknown"
                )
                tracked_skipped_fields.append(f"{original_name} (Type: {type_name})")
                # Remove from mappings if skipped
                del self._field_name_mapping[original_name]
                del self._normalized_to_original[normalized_name]

        # Report renamed fields
        if tracked_renamed_fields and self.feedback:
            self.feedback.pushInfo(
                self.tr(
                    "The following field names were normalized for PostgreSQL compatibility:"
                )
            )
            for renamed in tracked_renamed_fields:
                self.feedback.pushInfo(f"  - {renamed}")

        # Report skipped fields
        if tracked_skipped_fields and self.feedback:
            self.feedback.pushWarning(
                self.tr(
                    "The following fields were skipped due to unsupported data types:"
                )
            )
            for skipped in tracked_skipped_fields:
                self.feedback.pushWarning(f"  - {skipped}")

    def _normalize_field_name(self, name: str) -> str:
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

        # Handle empty name and names starting with digits differently
        if not normalized:
            # If the name is empty, assign a sequential number starting from 1
            # Example: "" → "field_1", "" → "field_2", etc.
            normalized = "field_" + str(self._empty_field_counter)
            self._empty_field_counter += 1

        if normalized and normalized[0].isdigit():
            # If the name starts with a digit after cleaning, prepend 'field_'
            # Example: "_field" → "field__field", "123abc" → "field_abc"
            normalized = "field_" + normalized

        # Limit length to PostgreSQL identifier limit
        # Example: "very_long_field_name_that_exceeds_postgresql_limit_of_63_chars" → "very_long_field_name_that_exceeds_postgresql_limit_of_63_ch"
        if len(normalized) > self.MAX_FIELD_LENGTH:
            normalized = normalized[: self.MAX_FIELD_LENGTH]

        # Handle reserved keywords by appending '_'
        # Example: "select" → "select_", "where" → "where_"
        if normalized in self.RESERVED_KEYWORDS:
            normalized = normalized + "_"
            # Recheck length
            if len(normalized) > self.MAX_FIELD_LENGTH:
                normalized = normalized[: self.MAX_FIELD_LENGTH - 1] + "_"

        # Final validation - if still invalid, use a generic name
        if not normalized or not re.match(r"^[a-z_][a-z0-9_]*$", normalized):
            normalized = "field"

        return normalized

    def _make_unique(self, base_name: str) -> str:
        """Make a field name unique by adding a suffix"""
        counter = 1
        normalized_name = base_name

        while normalized_name in self._normalized_columns:
            normalized_name = f"{base_name}_{counter}"
            if len(normalized_name) > self.MAX_FIELD_LENGTH:
                # Truncate base name to fit with suffix
                suffix_length = len(str(counter)) + 1  # +1 for underscore
                truncated_base = base_name[: self.MAX_FIELD_LENGTH - suffix_length]
                normalized_name = f"{truncated_base}_{counter}"
            counter += 1

        return normalized_name

    def _get_field_type(
        self, field: QgsField
    ) -> Optional[Literal["integer", "float", "boolean", "string"]]:
        """Get the field type as a string compatible with STRATO"""
        if field.type() == QMetaType.Int:
            return "integer"
        elif field.type() == QMetaType.Double or field.type() == QMetaType.Float:
            return "float"
        elif field.type() == QMetaType.Bool:
            return "boolean"
        elif field.type() == QMetaType.QString:
            return "string"
        else:
            return None

    def tr(self, string: str) -> str:
        """Translate string"""
        from qgis.PyQt.QtCore import QCoreApplication

        return QCoreApplication.translate("FieldNameNormalizer", string)
