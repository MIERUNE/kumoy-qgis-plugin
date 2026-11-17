from dataclasses import dataclass
from typing import List, Optional

from . import client
from ._util import UNSET, compact
from .models import Raster, RasterDetail, from_dict, list_of


def get_rasters(project_id: str) -> List[Raster]:
    return list_of(Raster, client.get(f"/project/{project_id}/raster"))


def get_raster(raster_id: str) -> RasterDetail:
    return from_dict(RasterDetail, client.get(f"/raster/{raster_id}"))


def get_download_url(raster_id: str) -> str:
    """Presigned GET URL of the COG, valid for one hour."""
    return client.get(f"/raster/{raster_id}/download")["url"]


@dataclass
class RasterUpload:
    raster_id: str
    # Presigned S3 PUT: Content-Type image/tiff and exactly `bytes` bytes
    upload_url: str


def create_raster(
    project_id: str, name: str, bytes: int, attribution: str = ""
) -> RasterUpload:
    data = client.post(
        f"/project/{project_id}/raster",
        {"name": name, "bytes": bytes, "attribution": attribution},
    )
    return RasterUpload(raster_id=data["rasterId"], upload_url=data["uploadUrl"])


def update_raster(
    raster_id: str, name: Optional[str] = UNSET, attribution: Optional[str] = UNSET
) -> Raster:
    data = client.put(
        f"/raster/{raster_id}", compact(name=name, attribution=attribution)
    )
    return from_dict(Raster, data)


def delete_raster(raster_id: str) -> None:
    client.delete(f"/raster/{raster_id}")
