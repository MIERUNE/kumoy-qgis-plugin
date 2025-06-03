import sys
from pathlib import Path

# Import FieldNameNormalizer directly to avoid provider dependencies
from processing.field_name_normalizer import FieldNameNormalizer

# Get the project root directory
project_root = Path(__file__).parent.parent

# Add project root to Python path
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Configure for package import
sys.modules["qgis_plugin"] = (
    sys.modules["__main__"] if "__main__" in sys.modules else None
)


__all__ = ["FieldNameNormalizer"]
