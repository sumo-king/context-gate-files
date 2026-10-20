"""Creating incidents.

STUB: keeps incidents in memory and makes up incident numbers, so the
customer form works before ServiceNow access is available. Later, replace
the body of create_incident() with a ServiceNow API call; the route that
calls it doesn't need to change.

Note: memory is cleared every time the app restarts.
"""
from itertools import count

from app.models.incident import IncidentCreate, IncidentCreated

_next_number = count(10001)
_incidents: dict[str, IncidentCreate] = {}


def create_incident(incident: IncidentCreate) -> IncidentCreated:
    number = f"INC{next(_next_number):07d}"   # e.g. INC0010001
    _incidents[number] = incident
    return IncidentCreated(
        number=number, category=incident.category, affected_ci=incident.affected_ci
    )


def get_incident(number: str) -> IncidentCreate | None:
    return _incidents.get(number)
