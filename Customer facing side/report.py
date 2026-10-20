"""Customer incident intake: pick the kind of problem, then fill in the form.

GET  /report                     -> choose what kind of problem (4 categories)
GET  /report?category=windows    -> the form for that category
POST /report                     -> validate against IncidentCreate
                                    invalid: form again, errors shown, answers
                                             kept (HTTP 422)
                                    valid:   create the incident, confirmation page
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from pydantic import ValidationError

from app.models.incident import (
    SYMPTOMS_BY_CATEGORY, BusinessImpact, Category, Environment, IncidentCreate, Symptom,
)
from app.services import incidents
from app.templating import templates

router = APIRouter()

# --- Wording per category -----------------------------------------------------
# Keys are the Category enum values the model accepts.
#   label / blurb  : shown on the "what kind of problem" page
#   noun           : used in headings ("Report a <noun> incident")
#   ci_label / ci_placeholder : the "affected thing" field differs per area
CATEGORIES = {
    Category.WINDOWS.value: {
        "label": "Windows server",
        "blurb": "RDP or login problems, Windows services, DNS/name issues, disk space",
        "noun": "Windows server",
        "ci_label": "Affected server",
        "ci_placeholder": "e.g. WINPRD-APP01",
    },
    Category.LINUX.value: {
        "label": "Linux server",
        "blurb": "SSH problems, services, file systems, disk space, performance",
        "noun": "Linux server",
        "ci_label": "Affected server",
        "ci_placeholder": "e.g. LNXPRD-DB01",
    },
    Category.VIRTUAL_MACHINE.value: {
        "label": "Virtual machine / hypervisor",
        "blurb": "A VM that won't start, snapshots, VM performance, host problems",
        "noun": "virtual machine",
        "ci_label": "Affected VM or host",
        "ci_placeholder": "e.g. VMPRD-APP01",
    },
    Category.STORAGE.value: {
        "label": "Storage & backup",
        "blurb": "Volumes, file shares, slow storage, full capacity, backups and restores",
        "noun": "storage or backup",
        "ci_label": "Affected storage resource",
        "ci_placeholder": "e.g. datastore, volume, share or backup job name",
    },
}

# Labels for every symptom. Which ones a customer sees depends on the category.
SYMPTOM_LABELS = {
    Symptom.UNREACHABLE: "Server unreachable / not responding",
    Symptom.REMOTE_ACCESS: "Can't log in remotely (RDP / SSH)",
    Symptom.NAME_RESOLUTION: "Works by IP address but not by name",
    Symptom.SLOW: "Slow / poor performance",
    Symptom.SERVICE_FAILED: "A service or application has stopped",
    Symptom.DISK_FULL: "Disk full",
    Symptom.READ_ONLY_FILESYSTEM: "File system is read-only",
    Symptom.VM_WONT_START: "VM won't start",
    Symptom.SNAPSHOT_ISSUE: "Snapshot problem",
    Symptom.VOLUME_UNAVAILABLE: "Volume or datastore unavailable",
    Symptom.SHARE_ACCESS: "Can't access a file share",
    Symptom.STORAGE_LATENCY: "Storage is slow (high latency)",
    Symptom.CAPACITY_FULL: "Storage capacity full",
    Symptom.BACKUP_FAILED: "Backup failed",
    Symptom.RESTORE_FAILED: "Restore failed",
    Symptom.OTHER: "Other",
}

# Labels for dropdowns that are the same for every category
COMMON_CHOICES = {
    "environment": {
        Environment.PROD.value: "Production",
        Environment.UAT.value: "UAT",
        Environment.DEV.value: "Development",
    },
    "business_impact": {
        BusinessImpact.HIGH.value: "High – many users or a critical service",
        BusinessImpact.MEDIUM.value: "Medium – one team or a non-critical service",
        BusinessImpact.LOW.value: "Low – single user, workaround available",
    },
}

# Every field the form sends; anything else posted is ignored
FORM_FIELDS = [
    "category", "affected_ci", "environment", "symptom", "started_at",
    "recent_changes", "change_details", "business_impact", "description",
]


# --- Routes -----------------------------------------------------------------

@router.get("", response_class=HTMLResponse)
async def show_form(request: Request, category: str = ""):
    """No category yet: ask what kind of problem. Otherwise show that category's form."""
    if category not in CATEGORIES:
        return render_picker(request)
    return render_form(request, category, values={"category": category}, errors={})


@router.post("", response_class=HTMLResponse)
async def submit_form(request: Request):
    """Validate the submission; re-show the form with errors or create the incident."""
    form = await request.form()

    # Keep exactly what the customer typed, so a failed submission
    # shows their answers again instead of an empty form
    values = {field: str(form.get(field, "")).strip() for field in FORM_FIELDS}

    try:
        incident = IncidentCreate.model_validate(to_model_input(values))
    except ValidationError as exc:
        errors = friendly_errors(exc)
        category = values["category"]
        if category not in CATEGORIES:
            # Without a valid category there's no form to show; go back a step
            return render_picker(request, error=True, status_code=422)
        return render_form(request, category, values, errors, status_code=422)

    created = incidents.create_incident(incident)
    return templates.TemplateResponse(
        request,
        "customer/report_done.html",
        {"incident": created, "category": CATEGORIES[created.category.value]},
    )


# --- Helpers ----------------------------------------------------------------

def render_picker(request: Request, error: bool = False, status_code: int = 200):
    return templates.TemplateResponse(
        request,
        "customer/report_choose.html",
        {"categories": CATEGORIES, "error": error},
        status_code=status_code,
    )


def render_form(request: Request, category: str, values: dict, errors: dict,
                status_code: int = 200):
    # Only offer the symptoms that belong to this category
    symptoms = {
        symptom.value: SYMPTOM_LABELS[symptom]
        for symptom in SYMPTOMS_BY_CATEGORY[Category(category)]
    }
    return templates.TemplateResponse(
        request,
        "customer/report.html",
        {
            "category_key": category,
            "category": CATEGORIES[category],
            "values": values,
            "errors": errors,
            "choices": {**COMMON_CHOICES, "symptom": symptoms},
        },
        status_code=status_code,
    )


def to_model_input(values: dict) -> dict:
    """Turn raw form strings into what the model expects.

    - Blank fields are left out, so the model reports them as missing
      (instead of a confusing "string too short" error).
    - The yes/no radio becomes a real True/False.
    """
    data = {key: value for key, value in values.items() if value != ""}
    if "recent_changes" in data:
        data["recent_changes"] = data["recent_changes"] == "yes"
    return data


def friendly_errors(exc: ValidationError) -> dict[str, str]:
    """Map Pydantic errors to {field_name: message} for the template.

    Field rules land on their field. Cross-field rules (model_validator)
    have no single field, so they go under "__form__" and show at the top.
    """
    errors: dict[str, str] = {}
    for error in exc.errors():
        field = str(error["loc"][0]) if error["loc"] else "__form__"
        errors.setdefault(field, message_for(error))   # first error per field wins
    return errors


def message_for(error: dict) -> str:
    """Plain-language message for one Pydantic error."""
    kind = error["type"]
    ctx = error.get("ctx", {})

    if kind == "missing":
        return "This field is required."
    if kind == "enum":
        return "Please choose one of the options."
    if kind == "string_too_short":
        return f"Please enter at least {ctx.get('min_length')} characters."
    if kind == "string_too_long":
        return f"Please keep this under {ctx.get('max_length')} characters."
    if kind == "string_pattern_mismatch":
        return "Use letters, numbers, hyphens, dots and underscores only."
    if kind.startswith("datetime"):
        return "Please enter a valid date and time."
    if kind == "value_error":
        # Our own messages from the model, minus Pydantic's "Value error, " prefix
        return str(ctx.get("error", error["msg"]))
    return error["msg"]
