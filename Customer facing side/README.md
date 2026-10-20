# Incident Context Gate (Proof of Concept)

Enforcing proper context at incident **intake** and proper **closure** in ServiceNow, so incidents are resolved faster and closed with an auditable record.

> **Status:** Proof of concept · **Target demo:** 15 November 2026 · **Team:** 7

---

## The problem

- Incidents arrive with too little information (which server, which environment, since when, what changed), so the first stretch of every incident goes to back-and-forth.
- Tickets bounce between resolver groups because they're miscategorised.
- Engineers close incidents without confirming with the customer, and closure notes are often just "resolved", which gives auditors and future engineers nothing to work with.

## What this PoC does

1. **Smart intake** – a category-specific form with mandatory, structured fields (CI picked from the CMDB, not free text).
2. **Automatic enrichment** – on submission, a service scans the affected server and attaches findings to the incident.
3. **Triage and suggestions** – rules (and optionally an approved AI model) suggest fixes or ask for missing details.
4. **Escalation** – low-confidence or unresolved cases are routed to engineers with all gathered context.
5. **Enforced closure** – engineers can only *resolve*; the customer (or an auto-close timer) *closes*.

### PoC scope

Four categories, matching the areas the Compute Engineering team supports:

| Category | Examples |
|---|---|
| Windows server | RDP/login failures, name-resolution problems, stopped services, disk space |
| Linux server | SSH failures, stopped services, read-only file systems, disk space |
| Virtual machine / hypervisor | VM won't start, snapshot problems, VM performance, host issues |
| Storage & backup | Unavailable volumes or shares, high latency, full capacity, failed backups and restores |

The customer picks the category first, then sees a form that only offers symptoms and wording for that area. Further categories (for example networking or databases) come after the PoC proves value.

**Depth per category:** the server scan is built end to end for **one** category first (Windows, since it matches the most common real tickets), with the other three starting on intake enforcement, rules-based suggestions and closure enforcement. See *Server scan by category* below.

---

## Incident lifecycle

```
New ──► In Progress ──► Resolved ──► Customer confirms? ──Yes──► Closed
                ▲                          │
                │                          No (reason required)
                └──── Reopened ◄───────────┘
                         │
                 reopen count ≥ 2 ──► Escalate (team lead / problem mgmt)

Resolved + no customer response in N business days ──► Auto-closed
```

**Principle:** the engineer resolves, the customer (or the clock) closes.

---

## Architecture

```
ServiceNow                                   Enrichment Service (Python/FastAPI)
┌──────────────────────────────┐             ┌────────────────────────────────┐
│ Record Producer (intake form)│             │ CMDB lookup (CI details)       │
│ UI Policies (dynamic fields) │──REST call─►│ Recent change records          │
│ Business Rules / Flows       │             │ vCenter scan (state, CPU/mem,  │
│ Closure gate + ACLs          │◄─work note──│   snapshots, alarms)           │
│ Auto-close + notifications   │             │ Rules engine / AI suggestions  │
└──────────────────────────────┘             └────────────────────────────────┘
```

### Components

| Component | Where | Purpose |
|---|---|---|
| Intake record producer | ServiceNow | Category-specific form with mandatory fields |
| UI policies | ServiceNow | Show/require fields based on earlier answers |
| Enrichment trigger | ServiceNow Flow / Business Rule | Calls the enrichment service on submit |
| Enrichment service | External (Python) | Gathers CMDB, change and vCenter data |
| Triage rules | Enrichment service | Maps scan findings to suggested fixes / escalation |
| Closure gate | ServiceNow Business Rule + ACL | Blocks *Resolved* without required fields; blocks engineers from setting *Closed* |
| Confirmation flow | ServiceNow notification + Flow | Accept / Reject on resolution; reopen handling |
| Auto-close | ServiceNow property + scheduled job | Closes resolved incidents after N business days with no response |

---

## Intake fields

| Field | Type | Required |
|---|---|---|
| Category | Choice (Windows / Linux / Virtual machine / Storage & backup) | Yes |
| Affected server, VM or storage resource | Reference (CMDB CI) | Yes |
| Environment | Choice (Prod / UAT / Dev) | Yes |
| Symptom | Choice, depends on category (see below) | Yes |
| Started at | Date/time | Yes |
| Recent changes known? | Yes/No + details | Yes |
| Business impact | Choice | Yes |
| Description | Text | Yes |

Symptoms offered per category:

| Category | Symptoms |
|---|---|
| Windows server | Unreachable · Can't log in remotely (RDP) · Works by IP but not by name · Slow · Service stopped · Disk full · Other |
| Linux server | Unreachable · Can't log in remotely (SSH) · Works by IP but not by name · Slow · Service stopped · Disk full · File system read-only · Other |
| Virtual machine | Unreachable · VM won't start · Snapshot problem · Slow · Disk full · Other |
| Storage & backup | Volume/datastore unavailable · Can't access a share · High latency · Capacity full · Backup failed · Restore failed · Other |

> P1 incidents are never blocked on missing context; context is chased in parallel.

## Server scan by category

The scan that runs on submission depends on the category (proposed checks; confirm what access each needs):

| Category | Checks |
|---|---|
| Windows server | CMDB record, recent changes, ping, forward and reverse DNS lookup, RDP port reachable, compare "by IP" against "by name" |
| Linux server | CMDB record, recent changes, ping, DNS lookups, SSH port reachable |
| Virtual machine | CMDB record, recent changes, vCenter: power state, CPU/memory, snapshots, alarms |
| Storage & backup | CMDB record, recent changes, capacity and latency from the array or datastore, last backup job status |

## Closure fields

| Field | Required to set *Resolved* |
|---|---|
| Resolution code | Yes |
| Root cause category | Yes |
| Resolution notes (structured, minimum length) | Yes |
| Linked change record | If a change was involved |

---

## Closure rules

- Resolver group **cannot** set state to *Closed* (ACL).
- On *Resolved*, the caller is notified with **Accept** / **Reject**.
- **Reject** requires a reason → state returns to *In Progress*, reassigned to the same engineer, reopen counter +1.
- **Reopen count ≥ 2** → notify team lead and flag for problem management.
- **No response** after N business days (to be agreed, typically 3–5) → auto-close, with a reminder sent beforehand.
- **Team-raised incidents:** the original caller accepts; fallback is the team's group manager.

---

## Getting started

### Prerequisites

- ServiceNow dev instance (or a free Personal Developer Instance with mocked data)
- API credentials for ServiceNow (integration user)
- Read-only vCenter API / PowerCLI access to a non-production environment
- Python 3.11+

### Run the enrichment service locally

```bash
git clone <repo-url>
cd incident-context-gate
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in ServiceNow + vCenter settings
uvicorn app.main:app --reload
```

### Environment variables

| Variable | Description |
|---|---|
| `SN_INSTANCE_URL` | ServiceNow instance URL |
| `SN_USERNAME` / `SN_PASSWORD` | Integration user credentials |
| `VCENTER_HOST` | vCenter host |
| `VCENTER_USERNAME` / `VCENTER_PASSWORD` | Read-only vCenter account |
| `AI_ENABLED` | `true` to enable AI suggestions (approved provider only) |

> Never commit credentials. Use the bank's approved secrets store outside local dev.

---

## Measuring success

Baseline these **before** the PoC, then compare after:

- Mean time to resolve (MTTR)
- Reassignments per incident
- Count of "awaiting info" transitions
- Reopen rate
- Time from *Resolved* to *Closed*
- % closed by customer acceptance vs auto-close
- % of resolutions with complete notes

**Demo approach:** replay 10–20 real historical incidents (a few from each category) through the PoC and compare against how they actually played out.

---

## Plan

| Week | Focus |
|---|---|
| 1 | Access requests, baseline metrics, finalise fields |
| 2–3 | Intake form + closure gate · enrichment service + vCenter/CMDB lookups · rules and suggestions |
| 4 | End-to-end integration in dev instance |
| 5 | Test with replayed historical incidents, refine |
| 6 | Demo with before/after comparison |

---

## Risks

- **Access and approvals** in a banking environment can take weeks – request early.
- **Form friction** may push users to bypass ServiceNow – keep fields minimal and auto-fill where possible.
- **AI usage** must use an approved provider; the rules engine alone is a valid PoC.
- **Wider scope means thinner depth.** Four categories at once risks four half-finished scans. Build the scan end to end for one category first and keep the others to intake, rules and closure until that works.
- **Overlap with native ServiceNow features** – confirm with the platform team what's already configured.

## Out of scope (for the PoC)

- Categories other than Windows server, Linux server, virtual machine and storage & backup
- Production deployment
- Full AI-driven auto-remediation
