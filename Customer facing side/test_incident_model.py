"""Tests for the customer intake rules in app/models/incident.py."""
from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from app.models.incident import SYMPTOMS_BY_CATEGORY, Category, IncidentCreate, Symptom


def valid_data(**overrides):
    """A complete incident; pass keyword arguments to change single fields."""
    data = {
        "category": "windows",
        "affected_ci": "winprd-app01",
        "environment": "prod",
        "symptom": "unreachable",
        "started_at": "2026-10-13T08:30:00",
        "recent_changes": False,
        "business_impact": "high",
        "description": "Server not responding to ping or RDP since 08:30.",
    }
    data.update(overrides)
    return data


# --- Happy path -------------------------------------------------------------

def test_complete_incident_is_accepted():
    incident = IncidentCreate(**valid_data())
    assert incident.category is Category.WINDOWS
    assert incident.symptom is Symptom.UNREACHABLE


def test_ci_name_is_uppercased_and_trimmed():
    incident = IncidentCreate(**valid_data(affected_ci="  winprd-app01 "))
    assert incident.affected_ci == "WINPRD-APP01"


def test_real_world_example_name_resolution_failure():
    """Windows server reachable by IP but not by name (a real ticket pattern)."""
    incident = IncidentCreate(**valid_data(
        symptom="name_resolution",
        description="Cannot RDP by name. Works via IP and DNS record exists.",
    ))
    assert incident.symptom is Symptom.NAME_RESOLUTION


# --- Categories and symptoms ---------------------------------------------------

@pytest.mark.parametrize(
    "category,symptom",
    [(category.value, symptom.value)
     for category, symptoms in SYMPTOMS_BY_CATEGORY.items()
     for symptom in symptoms if symptom is not Symptom.OTHER],
)
def test_every_offered_symptom_is_accepted_for_its_category(category, symptom):
    assert IncidentCreate(**valid_data(category=category, symptom=symptom))


@pytest.mark.parametrize(
    "category,symptom",
    [("storage", "remote_access"),       # can't RDP into a storage array
     ("windows", "backup_failed"),       # backups belong to storage
     ("linux", "vm_wont_start"),         # VM problems belong to virtual_machine
     ("virtual_machine", "share_access")],
)
def test_symptom_from_another_category_is_rejected(category, symptom):
    with pytest.raises(ValidationError, match="doesn't apply"):
        IncidentCreate(**valid_data(category=category, symptom=symptom))


def test_unknown_category_is_rejected():
    with pytest.raises(ValidationError):
        IncidentCreate(**valid_data(category="mainframe"))


def test_every_category_offers_an_other_option():
    for symptoms in SYMPTOMS_BY_CATEGORY.values():
        assert Symptom.OTHER in symptoms


def test_every_symptom_is_used_by_some_category():
    used = {s for symptoms in SYMPTOMS_BY_CATEGORY.values() for s in symptoms}
    assert used == set(Symptom)


# --- Missing context is rejected ---------------------------------------------

@pytest.mark.parametrize(
    "field",
    ["category", "affected_ci", "environment", "symptom", "started_at",
     "recent_changes", "business_impact", "description"],
)
def test_each_required_field_is_enforced(field):
    data = valid_data()
    data.pop(field)
    with pytest.raises(ValidationError) as exc:
        IncidentCreate(**data)
    assert field in str(exc.value)


def test_description_too_short_is_rejected():
    with pytest.raises(ValidationError):
        IncidentCreate(**valid_data(description="broken"))


# --- Bad values are rejected --------------------------------------------------

def test_unknown_environment_is_rejected():
    with pytest.raises(ValidationError):
        IncidentCreate(**valid_data(environment="staging"))


def test_invalid_ci_name_is_rejected():
    with pytest.raises(ValidationError):
        IncidentCreate(**valid_data(affected_ci="my server!"))


def test_underscores_are_allowed_in_ci_names():
    # Storage resources and backup jobs often use underscores
    incident = IncidentCreate(**valid_data(category="storage", symptom="backup_failed",
                                           affected_ci="bkp_job_nightly"))
    assert incident.affected_ci == "BKP_JOB_NIGHTLY"


def test_future_start_time_is_rejected():
    tomorrow = (datetime.now() + timedelta(days=1)).isoformat()
    with pytest.raises(ValidationError, match="future"):
        IncidentCreate(**valid_data(started_at=tomorrow))


# --- Rules across fields --------------------------------------------------------

def test_recent_change_requires_details():
    with pytest.raises(ValidationError, match="recent change"):
        IncidentCreate(**valid_data(recent_changes=True))


def test_recent_change_with_details_is_accepted():
    incident = IncidentCreate(
        **valid_data(recent_changes=True, change_details="Patched OS last night")
    )
    assert incident.change_details == "Patched OS last night"


def test_other_symptom_needs_longer_description():
    with pytest.raises(ValidationError, match="50 characters"):
        IncidentCreate(**valid_data(symptom="other", description="Something odd is happening."))
