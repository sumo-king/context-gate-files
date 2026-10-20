"""Tests for the customer intake form (app/web/report.py)."""
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.models.incident import SYMPTOMS_BY_CATEGORY, Category, Symptom
from app.web.report import CATEGORIES

CATEGORY_KEYS = [category.value for category in Category]


# --- Step 1: choosing the kind of problem ----------------------------------------

def test_report_page_asks_for_a_category(client):
    response = client.get("/report")
    assert response.status_code == 200
    assert "What kind of problem is it?" in response.text
    for key in CATEGORY_KEYS:
        assert f'href="/report?category={key}"' in response.text


def test_unknown_category_falls_back_to_the_picker(client):
    response = client.get("/report?category=mainframe")
    assert response.status_code == 200
    assert "What kind of problem is it?" in response.text


# --- Step 2: the form for each category --------------------------------------------

@pytest.mark.parametrize("key", CATEGORY_KEYS)
def test_form_loads_for_each_category(client, key):
    response = client.get(f"/report?category={key}")
    assert response.status_code == 200
    assert f"Report a {CATEGORIES[key]['noun']} incident" in response.text
    assert f'name="category" value="{key}"' in response.text       # carried to the POST
    assert CATEGORIES[key]["ci_label"] in response.text
    assert 'value="prod"' in response.text                          # shared dropdowns


@pytest.mark.parametrize("key", CATEGORY_KEYS)
def test_form_only_offers_that_categorys_symptoms(client, key):
    html = client.get(f"/report?category={key}").text
    offered = SYMPTOMS_BY_CATEGORY[Category(key)]
    for symptom in Symptom:
        present = f'<option value="{symptom.value}"' in html
        assert present == (symptom in offered), f"{symptom.value} wrong for {key}"


# --- Valid submission ---------------------------------------------------------

def test_complete_submission_creates_incident(client, complete_form):
    response = client.post("/report", data=complete_form)
    assert response.status_code == 200
    assert "Incident submitted" in response.text
    assert "INC00" in response.text
    assert "WINPRD-APP01" in response.text          # normalised by the model


@pytest.mark.parametrize("key", CATEGORY_KEYS)
def test_a_valid_incident_can_be_submitted_for_each_category(client, complete_form, key):
    complete_form["category"] = key
    complete_form["symptom"] = SYMPTOMS_BY_CATEGORY[Category(key)][0].value
    response = client.post("/report", data=complete_form)
    assert response.status_code == 200
    assert "Incident submitted" in response.text


def test_windows_name_resolution_ticket_is_accepted(client, complete_form):
    complete_form["symptom"] = "name_resolution"
    complete_form["description"] = "Cannot RDP by name; works by IP and the DNS record exists."
    assert client.post("/report", data=complete_form).status_code == 200


def test_each_submission_gets_a_new_number(client, complete_form):
    first = client.post("/report", data=complete_form).text
    second = client.post("/report", data=complete_form).text
    assert first != second


# --- Missing context is enforced --------------------------------------------------

def test_submission_without_a_category_goes_back_to_the_picker(client, complete_form):
    complete_form["category"] = ""
    response = client.post("/report", data=complete_form)
    assert response.status_code == 422
    assert "Please choose what kind of problem" in response.text


def test_empty_submission_goes_back_to_the_picker(client):
    response = client.post("/report", data={})
    assert response.status_code == 422
    assert "Please choose what kind of problem" in response.text


def test_category_only_submission_flags_every_other_required_field(client):
    response = client.post("/report", data={"category": "windows"})
    assert response.status_code == 422
    assert "Please fix the highlighted fields" in response.text
    assert response.text.count("This field is required.") == 7


@pytest.mark.parametrize(
    "field",
    ["affected_ci", "environment", "symptom", "started_at",
     "recent_changes", "business_impact", "description"],
)
def test_blank_required_field_is_flagged(client, complete_form, field):
    complete_form[field] = ""
    response = client.post("/report", data=complete_form)
    assert response.status_code == 422
    assert "This field is required." in response.text


def test_answers_are_kept_after_an_error(client, complete_form):
    complete_form["description"] = "too short"
    response = client.post("/report", data=complete_form)
    assert response.status_code == 422
    assert 'name="category" value="windows"' in response.text     # still the Windows form
    assert 'value="winprd-app01"' in response.text                 # text input kept
    assert '<option value="prod" selected>' in response.text      # dropdown kept
    assert re.search(r'value="no"\s+checked', response.text)       # radio kept
    assert "too short" in response.text                            # textarea kept
    assert "at least 20 characters" in response.text


# --- Friendly messages for specific rules -------------------------------------------

def test_symptom_from_another_category_shows_message(client, complete_form):
    complete_form["category"] = "storage"
    complete_form["symptom"] = "remote_access"       # makes no sense for storage
    response = client.post("/report", data=complete_form)
    assert response.status_code == 422
    assert "doesn&#39;t apply" in response.text or "doesn't apply" in response.text


def test_recent_change_without_details_shows_message(client, complete_form):
    complete_form["recent_changes"] = "yes"
    response = client.post("/report", data=complete_form)
    assert response.status_code == 422
    assert "Please describe the recent change" in response.text


def test_invalid_name_shows_message(client, complete_form):
    complete_form["affected_ci"] = "my server!"
    response = client.post("/report", data=complete_form)
    assert "letters, numbers, hyphens, dots and underscores" in response.text


def test_future_start_time_is_rejected(client, complete_form):
    complete_form["started_at"] = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    response = client.post("/report", data=complete_form)
    assert response.status_code == 422
    assert "can&#39;t be in the future" in response.text or "can't be in the future" in response.text


def test_recent_local_time_is_not_treated_as_future(client, complete_form):
    # 10 minutes ago in South African time must be accepted, even on a UTC server
    sast_now = datetime.now(ZoneInfo("Africa/Johannesburg"))
    complete_form["started_at"] = (sast_now - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M")
    response = client.post("/report", data=complete_form)
    assert response.status_code == 200


def test_user_input_is_escaped(client, complete_form):
    complete_form["description"] = "<script>alert('x')</script> plus enough text"
    complete_form["affected_ci"] = ""        # force the form to re-render
    response = client.post("/report", data=complete_form)
    assert "<script>alert" not in response.text
