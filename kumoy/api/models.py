"""Response models of the Kumoy API and the dict -> dataclass parser.

Field names follow the API (camelCase) so a model reads like the backend's
schema. A field without a default is required: when the server omits it,
parsing fails loudly instead of filling in a placeholder that would surface
later as an empty name or a wrong role.
"""

import dataclasses
import sys
import typing
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Type, TypeVar

T = TypeVar("T")

Role = Literal["OWNER", "ADMIN", "MEMBER"]
GeometryType = Literal["POINT", "LINESTRING", "POLYGON"]


def from_dict(cls: Type[T], data: Any) -> T:
    """Build `cls` (a dataclass) from a decoded JSON object.

    Handles nested dataclasses, Optional[...] and List[...]. Unknown keys are
    ignored so the server can add fields without breaking older plugins.
    """
    if not isinstance(data, dict):
        raise ValueError(f"Expected an object for {cls.__name__}, got {type(data)}")
    hints = typing.get_type_hints(cls, vars(sys.modules[cls.__module__]))
    kwargs = {}
    for f in dataclasses.fields(cls):
        if f.name in data:
            kwargs[f.name] = _convert(hints[f.name], data[f.name])
        elif (
            f.default is dataclasses.MISSING
            and f.default_factory is dataclasses.MISSING
        ):
            raise ValueError(f"{cls.__name__}.{f.name} is missing in the response")
    return cls(**kwargs)


def _convert(tp: Any, value: Any) -> Any:
    if value is None:
        return None
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if origin is typing.Union:
        inner = [a for a in args if a is not type(None)]
        return _convert(inner[0], value) if len(inner) == 1 else value
    if origin in (list, List):
        return [_convert(args[0], v) for v in value] if args else list(value)
    if dataclasses.is_dataclass(tp):
        return from_dict(tp, value)
    if tp is float and isinstance(value, int):
        return float(value)
    return value


def list_of(cls: Type[T], data: Any) -> List[T]:
    return [from_dict(cls, item) for item in (data or [])]


def is_editor(role: Optional[str]) -> bool:
    """Team ADMIN (and the legacy OWNER) may write; MEMBER is read-only."""
    return role in ("ADMIN", "OWNER")


# --- Organization / team / project -----------------------------------------


@dataclass
class Organization:
    id: str
    name: str
    subscriptionPlan: str = ""
    storageUnits: float = 0
    createdAt: str = ""
    updatedAt: str = ""


@dataclass
class OrganizationWithRole(Organization):
    role: Role = "MEMBER"
    # Set while the organization awaits deletion; its projects answer 404
    scheduledDeletionAt: Optional[str] = None


@dataclass
class OrganizationUsage:
    projects: int = 0
    vectors: int = 0
    rasters: int = 0
    styledMaps: int = 0
    organizationMembers: int = 0
    organizationInvites: int = 0
    organizationEditors: int = 0
    organizationEditorInvites: int = 0
    usedStorageUnits: float = 0


@dataclass
class PlanSettings:
    maxProjects: int = 0
    maxVectors: int = 0
    maxRasters: int = 0
    maxStyledMaps: int = 0
    maxTeams: int = 0
    maxOrganizationMembers: int = 0
    maxEditors: int = 0
    maxVectorFeatures: int = 0
    maxVectorAttributes: int = 0
    defaultStorageUnits: float = 0
    activityLogViewableDays: int = 0
    canUseKeyphrase: bool = False
    canEditFeaturesOnWeb: bool = False


@dataclass
class OrganizationDetail(OrganizationWithRole):
    usage: OrganizationUsage = field(default_factory=OrganizationUsage)
    planSettings: PlanSettings = field(default_factory=PlanSettings)
    availableStorageUnits: float = 0
    availableEditors: int = 0


@dataclass
class Team:
    id: str
    name: str
    organizationId: str = ""
    organization: Optional[Organization] = None
    createdAt: str = ""
    updatedAt: str = ""


@dataclass
class TeamWithRole(Team):
    role: Role = "MEMBER"


@dataclass
class Project:
    id: str
    name: str
    description: Optional[str] = ""
    teamId: str = ""
    team: Optional[Team] = None
    thumbnailImageUrl: Optional[str] = None
    createdAt: str = ""
    updatedAt: str = ""


@dataclass
class ProjectInOrganization(Project):
    vectorCount: int = 0
    rasterCount: int = 0
    mapCount: int = 0
    storageUnitsSum: float = 0
    isBookmarked: bool = False


@dataclass
class ProjectDetail(Project):
    role: Role = "MEMBER"
    storageUnitsSum: float = 0


# --- Data -------------------------------------------------------------------


@dataclass
class Column:
    name: str
    type: str  # integer | float | string | boolean


@dataclass
class Vector:
    id: str
    name: str
    type: GeometryType
    projectId: str = ""
    attribution: Optional[str] = ""
    storageUnits: float = 0
    createdAt: str = ""
    updatedAt: str = ""


@dataclass
class VectorDetail(Vector):
    role: Role = "MEMBER"
    extent: List[float] = field(default_factory=list)
    count: int = 0
    columns: List[Column] = field(default_factory=list)


@dataclass
class Raster:
    id: str
    name: str
    projectId: str = ""
    attribution: Optional[str] = ""
    storageUnits: float = 0
    createdAt: str = ""
    updatedAt: str = ""


@dataclass
class RasterDetail(Raster):
    role: Role = "MEMBER"
    bandCount: int = 0
    # OK | NOT_FOUND | INVALID | UNKNOWN
    fileStatus: str = "UNKNOWN"


@dataclass
class StyledMap:
    id: str
    name: str
    projectId: str = ""
    description: Optional[str] = ""
    isPublic: bool = False
    attribution: Optional[str] = ""
    assetsHash: Optional[str] = None
    thumbnailImageUrl: Optional[str] = None
    createdAt: str = ""
    updatedAt: str = ""


@dataclass
class StyledMapDetail(StyledMap):
    """GET /_qgis/styled-map/{id}: the map with its QGIS project XML."""

    qgisproject: str = ""
    role: Role = "MEMBER"
    # Carries project.team.organizationId, to select the map's project
    project: Optional[Project] = None


# --- User / misc -----------------------------------------------------------


@dataclass
class User:
    id: str
    name: Optional[str] = ""
    email: Optional[str] = ""
    avatarImage: Optional[str] = None
    createdAt: str = ""
    updatedAt: str = ""


@dataclass
class PublicParams:
    minQgisPluginVersion: Optional[str] = None


@dataclass
class PresignedPost:
    url: str
    filename: str
    fields: Dict[str, str] = field(default_factory=dict)
