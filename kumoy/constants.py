"""Constants shared across the plugin."""

PLUGIN_NAME = "Kumoy"

# QgsMessageLog category
LOG_CATEGORY = PLUGIN_NAME

# Path of the root item in the Browser panel
BROWSER_ROOT_PATH = "kumoy:/"

DATA_PROVIDER_KEY = "kumoy"
DATA_PROVIDER_DESCRIPTION = "Kumoy Data Provider"

# Rasters use their own provider key: QGIS binds a key to either a vector or
# a raster provider, so sharing "kumoy" with vectors is not possible.
RASTER_DATA_PROVIDER_KEY = "kumoyraster"
RASTER_DATA_PROVIDER_DESCRIPTION = "Kumoy Raster Data Provider"

# Maximum lengths enforced by the server
MAX_CHARACTERS_ORGANIZATION_NAME = 32
MAX_CHARACTERS_PROJECT_NAME = 32
MAX_CHARACTERS_PROJECT_DESCRIPTION = 255
MAX_CHARACTERS_VECTOR_NAME = 32
MAX_CHARACTERS_VECTOR_ATTRIBUTION = 255
MAX_CHARACTERS_RASTER_NAME = 32
MAX_CHARACTERS_RASTER_ATTRIBUTION = 255
MAX_CHARACTERS_STYLEDMAP_NAME = 32
MAX_CHARACTERS_STYLEDMAP_ATTRIBUTION = 255
MAX_CHARACTERS_STYLEDMAP_DESCRIPTION = 255

# Server-side limits
MAX_CHARACTERS_STRING_FIELD = 255
MAX_WKB_LENGTH = 10_000_000  # max length of a base64-encoded WKB

# Raster (COG) upload limit. COGs are written as classic GeoTIFF (no BigTIFF),
# so cap below its 4 GiB limit at 4 GB (decimal), which also fits a single S3
# PUT (5 GiB). Outputs between this and 4 GiB are rejected by their converted
# size; larger ones cannot be written as classic TIFF and fail in conversion.
MAX_RASTER_UPLOAD_BYTES = 4_000_000_000

# Prefix of field names reserved by Kumoy
RESERVED_FIELD_NAME_PREFIX = "kumoy_"

DOCUMENTATION_URL = "https://docs.kumoy.io/"
