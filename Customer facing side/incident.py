"""What a complete customer incident report looks like.

This model is the single source of truth for "enough context". The intake
form, the report route and the tests all rely on it, so a rule changed here
changes everywhere.
"""
from datetime import datetime, timezone
from enum import Enum
from zoneinfo import ZoneInfo

from pydantic import (
    BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator,
)


# Customers enter times in South African time
LOCAL_TZ = ZoneInfo("Africa/Johannesburg")


# --- Allowed values -------------------------------------------------------
# Enums keep choices consistent between the form dropdowns and validation.
# The value (right side) is what's stored/sent; the form can show nicer labels.

class Environment(str, Enum):
    PROD = "prod"
    UAT = "uat"
    DEV = "dev"


class Category(str, Enum):
    """Which area of the platform is affected. Decides which team gets it
    and which symptoms the customer can pick from."""
    WINDOWS = "windows"
    LINUX = "linux"
    VIRTUAL_MACHINE = "virtual_machine"
    STORAGE = "storage"


class Symptom(str, Enum):
    # Shared by several categories
    UNREACHABLE = "unreachable"
    SLOW = "slow"
    DISK_FULL = "disk_full"
    SERVICE_FAILED = "service_failed"
    OTHER = "other"
    # Windows and Linux
    REMOTE_ACCESS = "remote_access"            # can't RDP / SSH in
    NAME_RESOLUTION = "name_resolution"        # works by IP, fails by name
    READ_ONLY_FILESYSTEM = "read_only_filesystem"
    # Virtual machine
    VM_WONT_START = "vm_wont_start"
    SNAPSHOT_ISSUE = "snapshot_issue"
    # Storage and backup
    VOLUME_UNAVAILABLE = "volume_unavailable"
    SHARE_ACCESS = "share_access"
    STORAGE_LATENCY = "storage_latency"
    CAPACITY_FULL = "capacity_full"
    BACKUP_FAILED = "backup_failed"
    RESTORE_FAILED = "restore_failed"


# Which symptoms each category offers (order = order shown on the form).
# The form and the validation both read this, so they can't disagree.
SYMPTOMS_BY_CATEGORY: dict[Category, tuple[Symptom, ...]] = {
    Category.WINDOWS: (
        Symptom.UNREACHABLE, Symptom.REMOTE_ACCESS, Symptom.NAME_RESOLUTION,
        Symptom.SLOW, Symptom.SERVICE_FAILED, Symptom.DISK_FULL, Symptom.OTHER,
    ),
    Category.LINUX: (
        Symptom.UNREACHABLE, Symptom.REMOTE_ACCESS, Symptom.NAME_RESOLUTION,
        Symptom.SLOW, Symptom.SERVICE_FAILED, Symptom.DISK_FULL,
        Symptom.READ_ONLY_FILESYSTEM, Symptom.OTHER,
    ),
    Category.VIRTUAL_MACHINE: (
        Symptom.UNREACHABLE, Symptom.VM_WONT_START, Symptom.SNAPSHOT_ISSUE,
        Symptom.SLOW, Symptom.DISK_FULL, Symptom.OTHER,
    ),
    Category.STORAGE: (
        Symptom.VOLUME_UNAVAILABLE, Symptom.SHARE_ACCESS, Symptom.STORAGE_LATENCY,
        Symptom.CAPACITY_FULL, Symptom.BACKUP_FAILED, Symptom.RESTORE_FAILED,
        Symptom.OTHER,
    ),
}


class BusinessImpact(str, Enum):
    HIGH = "high"        # many users or a critical service affected
    MEDIUM = "medium"    # a team or non-critical service affected
    LOW = "low"          # single user, workaround available


# --- The intake model -----------------------------------------------------

class IncidentCreate(BaseModel):
    """Data a customer must supply when reporting an incident."""

    # Trim stray spaces from all text fields before validating
    model_config = ConfigDict(str_strip_whitespace=True)

    # Field order matters: category must come before symptom, because the
    # symptom check below needs to know the category.
    category: Category
    affected_ci: str = Field(
        min_length=3,
        max_length=63,
        # Name characters only. Later this becomes a CMDB lookup.
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_\-\.]*$",
        description="Server, VM or storage resource, as named in the CMDB",
    )
    environment: Environment
    symptom: Symptom
    started_at: datetime = Field(description="When the problem started")
    recent_changes: bool = Field(description="Was anything changed recently?")
    change_details: str | None = Field(default=None, max_length=1000)
    business_impact: BusinessImpact
    description: str = Field(min_length=20, max_length=4000)

    # --- Single-field rules ----------------------------------------------

    @field_validator("affected_ci")
    @classmethod
    def normalise_ci(cls, value: str) -> str:
        # CMDB names are case-insensitive; store them consistently
        return value.upper()

    @field_validator("symptom")
    @classmethod
    def symptom_matches_category(cls, value: Symptom, info: ValidationInfo) -> Symptom:
        # info.data holds the fields validated so far. If the category itself
        # was invalid it's missing here, and that error is reported instead.
        category = info.data.get("category")
        if category is not None and value not in SYMPTOMS_BY_CATEGORY[category]:
            raise ValueError("That problem type doesn't apply to this kind of incident")
        return value

    @field_validator("started_at")
    @classmethod
    def not_in_future(cls, value: datetime) -> datetime:
        # The form sends local time with no timezone (e.g. 2026-10-15T09:30).
        # Attach South African time so it compares correctly with "now",
        # whether the server runs on SAST (Windows) or UTC (EC2).
        if value.tzinfo is None:
            value = value.replace(tzinfo=LOCAL_TZ)
        if value > datetime.now(timezone.utc):
            raise ValueError("Start time can't be in the future")
        return value

    # --- Rules that depend on more than one field --------------------------

    @model_validator(mode="after")
    def check_dependent_fields(self) -> "IncidentCreate":
        # If the customer says something changed, they must say what
        if self.recent_changes and not self.change_details:
            raise ValueError("Please describe the recent change")

        # "Other" gives engineers nothing to triage on, so demand more detail
        if self.symptom is Symptom.OTHER and len(self.description) < 50:
            raise ValueError(
                "For 'Other' symptoms, describe the problem in at least 50 characters"
            )
        return self


class IncidentCreated(BaseModel):
    """What the app returns to the customer after a successful submission."""

    number: str               # e.g. INC0010001
    category: Category
    affected_ci: str
    status: str = "new"
