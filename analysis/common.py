"""Read the labeled JSONL and derive the measurements used by the analyses."""

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
INVOLVED = ("discovered", "assisted", "suspected")
OTHER = ("none", "unknown")
GROUPS = {"AI-discovered": ("discovered",), "AI-assisted": ("assisted",),
          "Suspected": ("suspected",), "AI-involved": INVOLVED, "Other": OTHER}
ELEMENTS = ["summary", "component", "trigger", "reproduction_steps",
            "observed_behavior", "expected_behavior", "environment"]
TASKS = ["Problem Diagnosis", "Fix Recommendation", "Report Writing",
         "Reproduction and Testing", "Information Retrieval", "Debugging Support"]
ORIGINS = ["Build / Installation", "Dynamic Analysis", "Fuzzing", "Source Code Review",
           "Static Analysis", "Testing", "Unknown", "Operational Usage"]
REASONS = ["Misuse", "Expected Behavior", "Unreproducible", "Incorrect Technical Claims",
           "Out-of-Scope", "Others"]
ACTIONS = ["Information Request", "Duplicate Checking", "Reproduction and Testing",
           "Code and API Investigation", "Fix Recommendation", "Patch Review and Testing"]
ACTION_KEYS = ["info", "dup", "repro", "code", "fix", "patch"]
BUGZILLA = "linux kernel (Bugzilla)"
OBSERVATION_END = datetime.fromisoformat("2026-10-23T07:56:51+00:00")


def quarter(month):
    return f"{month[:4]}Q{(int(month[5:7]) - 1) // 3 + 1}"


def read_reports(path):
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            report = json.loads(line)
            if report["is_bug_report"]["label"] != "yes":
                raise ValueError(f"Line {number}: expected a screened bug report")
            if not "2024-01-01" <= report["opened_time"] < "2026-10-01":
                raise ValueError(f"Line {number}: outside the study opening window")
            yield report


def write_csv(path, rows):
    rows = list(rows)
    if not rows:
        raise ValueError(f"No results to write to {path.name}")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def material_units(report):
    """Deduplicate eligible events by report-local material identity and type."""
    units = defaultdict(list)
    for event in report["handling_events"]:
        if event["included_in_analysis"]:
            units[event["material_type"], event["material"]].append(event)
    for (typ, _), events in units.items():
        explicit = {e["ai_generated"] for e in events if e["ai_generated"] is not None}
        origin = ("Conflicting" if len(explicit) > 1 else
                  "AI-generated" if explicit == {True} else "Other")
        actions = {e["action"] for e in events}
        action = ("Reject" if actions & {"Correct", "Refute"} else
                  "Request supplementation" if "Request supplementation" in actions else
                  "Use" if "Use" in actions else "None of three")
        yield dict(material_type=typ, quarter=quarter(report["opened_time"]),
                   origin=origin, action=action)


def load_data(path):
    """Return report measurements, matched replies, and material-unit counts.

    Categorical lists stay as lists/sets in memory. No intermediate input files
    or encoded masks are used. Observation fields contain no discussion text.
    """
    rows, replies, materials = [], [], Counter()
    seen = set()
    for report in read_reports(path):
        if report["id"] in seen:
            raise ValueError("Duplicate report ID")
        seen.add(report["id"])
        observed = report["observations"]
        opened = datetime.fromisoformat(report["opened_time"])
        closed = datetime.fromisoformat(report["closed_time"]) if report["closed_time"] else None
        counts, ai_counts, ai_actions = Counter(), Counter(), set()
        for label in report["maintainer_reply_labels"]:
            comment = label["observation"]
            if report["library"] == BUGZILLA or comment is None or comment["is_reporter"]:
                continue
            role = label["ai_role"] if label["ai_involved"] else "no_ai"
            if role not in ("ai_bot", "ai_assist", "no_ai"):
                raise ValueError("Unexpected maintainer AI role")
            actions = set(label["actions"])
            replies.append(dict(project=report["library"], report=report["id"],
                month=comment["created_at"][:7], role=role, actions=actions,
                account=comment.get("account_id")))
            if label["ai_involved"]:
                ai_counts[role] += 1
                ai_actions.update(actions)
            days = (datetime.fromisoformat(comment["created_at"]) - opened).total_seconds() / 86400
            if not comment["is_bot"] and 0 <= days <= 30:
                counts.update(actions)
        rows.append(dict(
            project=report["library"], language=report["language"], month=report["opened_time"][:7],
            role=report["report_ai"]["role"], origin=report["bug_origin"], quality=report["quality"],
            verdict=report["maintainer_verdict"], missing=report["missing_elements"],
            tasks=report["report_ai"]["tasks"], reasons=report["invalid_reasons"],
            reporter=observed["reporter_id"], characters=observed["report_characters"],
            followup_comments=observed["followup_comments"],
            eligible90=int(opened <= OBSERVATION_END - timedelta(days=90)),
            closure_day=max(0, (closed - opened).total_seconds() / 86400) if closed else -1,
            **{f"replies_{day}d": observed["maintainer_replies"][f"{day}d"] for day in (1, 7, 30)},
            **{"action_" + key: counts[action] for key, action in zip(ACTION_KEYS, ACTIONS)},
            ai_bot_replies=ai_counts["ai_bot"], ai_assist_replies=ai_counts["ai_assist"],
            ai_actions=ai_actions,
        ))
        for material in material_units(report):
            materials[tuple(material.values())] += 1
    if not rows:
        raise ValueError("The input contains no reports")
    material_counts = [dict(zip(("material_type", "quarter", "origin", "action"), key), count=count)
                       for key, count in sorted(materials.items())]
    return pd.DataFrame(rows), pd.DataFrame(replies), material_counts
