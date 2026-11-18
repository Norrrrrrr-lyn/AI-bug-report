"""Check full-run results against numerical values reported in the paper."""

import argparse
import csv
import hashlib
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=root / "data/labeled_reports.jsonl")
    parser.add_argument("--results", type=Path, default=root / "results")
    args = parser.parse_args()
    checks, failures = 0, []

    def check(name, actual, expected, digits=None):
        nonlocal checks
        checks += 1
        value = round(float(actual), digits) if digits is not None else actual
        if value != expected:
            failures.append(f"{name}: expected {expected}, got {actual}")

    def read(name):
        return json.loads((args.results / name).read_text(encoding="utf-8"))

    def table(name):
        with (args.results / name).open(encoding="utf-8", newline="") as stream:
            return list(csv.DictReader(stream))

    run = read("run.json")
    check("analyses", sorted(run["analyses"]), ["comparisons", "descriptive", "materials", "regression", "temporal"])
    check("bootstrap", run["bootstrap"], 5000)
    check("comparison seed", run["comparison_seed"], 20260101)
    check("temporal seed", run["temporal_seed"], 20261106)
    with args.input.open("rb") as stream:
        check("input matches results", hashlib.file_digest(stream, "sha256").hexdigest(), run["input_sha256"])
    profile = read("profile.json")
    for field, expected in dict(projects=101, reports=120918, github_reports=117499, followup_comments=503596).items():
        check(field, profile[field], expected)
    for role, expected in dict(assisted=2508, discovered=396, suspected=96, none=1142, unknown=116776).items():
        check(role, profile["roles"][role], expected)
    adoption = {r["period"]: r for r in table("adoption.csv")}
    check("AI-involved", int(adoption["all"]["ai_reports"]), 3000)
    check("reporter accounts", int(adoption["all"]["distinct_accounts"]), 2316)
    for year, accounts, projects in [("2024", 259, 55), ("2025", 708, 87), ("2026", 1385, 99)]:
        check(year + " reporter accounts", int(adoption[year]["distinct_accounts"]), accounts)
        check(year + " projects", int(adoption[year]["projects"]), projects)
    check("September AI reports", int(adoption["2026-09"]["ai_reports"]), 491)
    check("September reporter accounts", int(adoption["2026-09"]["distinct_accounts"]), 335)
    tasks = read("tasks.json")
    check("assisted with named tasks", tasks["with_task"], 2084)
    for task, percentage in [("Problem Diagnosis", 55.7), ("Fix Recommendation", 42.0),
                             ("Report Writing", 32.9), ("Reproduction and Testing", 12.7),
                             ("Information Retrieval", 10.3), ("Debugging Support", 8.8)]:
        check(task + " share", 100 * tasks["counts"][task] / tasks["with_task"], percentage, 1)
    check("diagnosis and fix cooccurrence", tasks["cooccurrence"]["Problem Diagnosis"]["Fix Recommendation"], 480)
    check("diagnosis and writing cooccurrence", tasks["cooccurrence"]["Problem Diagnosis"]["Report Writing"], 281)
    completeness = read("completeness.json")["matched"]
    check("matched strata", completeness["q_high"]["strata"], 550)
    check("high completeness delta", completeness["q_high"]["est"], 8.72, 2)
    check("missing elements delta", completeness["n_missing"]["est"], -.47, 2)
    validity = read("validity.json")
    check("valid among decided delta", validity["matched"]["v_dec_valid"]["est"], -.37, 2)
    check("discovered valid delta", validity["roles"]["discovered"]["v_valid"]["est"], -10.92, 2)
    check("discovered valid q", validity["roles"]["discovered"]["v_valid"]["q"], .033, 3)
    rejection = read("rejection_comparison.json")
    reason = rejection["matched"]["r_incorrect"]
    for key, expected in [("est", 4.02), ("lo", 1.06), ("hi", 8.03)]:
        check("incorrect claims " + key, reason[key], expected, 2)
    # Six of the 35 invalid suspected reports are labeled Out-of-Scope.
    check("Suspected invalid reports", rejection["groups"]["Suspected"]["n"], 35)
    check("Suspected Out-of-Scope labels", rejection["groups"]["Suspected"]["r_scope"], 17.14, 2)
    for name in ("closure.json", "replies.json"):
        groups = read(name)["groups"]
        check(name + " AI cohort", groups["AI-involved"]["n"], 2117)
        check(name + " Other cohort", groups["Other"]["n"], 109326)
    actions = read("actions.json")
    check("assisted actions delta", actions["roles"]["assisted"]["n_all"]["est"], .46, 2)
    check("assisted actions q", actions["roles"]["assisted"]["n_all"]["q"], .018, 3)
    regression = read("regression.json")
    for model in ("A", "B"):
        check(model + " sample", regression[model]["n"], 68773)
        check(model + " valid", regression[model]["valid"], 35419)
        check(model + " convergence", regression[model]["max_abs_adjusted_score"] < 1e-4, True)
    terms = {
        "A": {"origin[Source Code Review]": 2.82, "origin[Fuzzing]": 2.78,
              "origin[Testing]": 2.25, "origin[Dynamic Analysis]": 1.98,
              "origin[Build / Installation]": 1.19, "origin[Static Analysis]": 1.09,
              "task[Reproduction and Testing]": 2.25, "task[Problem Diagnosis]": 1.42,
              "task[Fix Recommendation]": 1.36, "task[Report Writing]": 1.05,
              "task[Information Retrieval]": .93, "task[Debugging Support]": .66,
              "quality[high]": 1.59, "quality[low]": .56},
        "B": {"missing[component]": .67, "missing[trigger]": .79, "missing[reproduction_steps]": .83,
              "missing[observed_behavior]": .83, "missing[expected_behavior]": .80,
              "missing[summary]": 1.02, "missing[environment]": 1.01},
    }
    for model, expected_terms in terms.items():
        for term, expected in expected_terms.items():
            check(model + " " + term, regression[model]["coefs"][term]["or"], expected, 2)

    materials = table("materials.csv")
    totals = {r["material_type"]: int(r["ai_n"]) + int(r["other_n"]) for r in materials}
    check("material units", sum(totals.values()), 76028)
    check("AI materials", sum(int(r["ai_n"]) for r in materials if r["action"] == "Reject"), 265)
    expected_materials = [
        ("Reproducer", 34, [(23.53, 5.14, 8.16, 3.15, 18.86), (38.24, 58.17, .52, .24, 1.09), (38.24, 27.47, 1.31, .60, 2.76)]),
        ("Technical claim", 148, [(59.46, 54.72, 1.57, 1.11, 2.23), (8.78, 12.49, .79, .41, 1.40), (6.76, 3.20, .92, .42, 1.78)]),
        ("Proposed fix", 83, [(54.22, 49.76, 1.55, .97, 2.48), (13.25, 16.63, .99, .47, 1.92), (16.87, 20.73, .49, .25, .90)]),
    ]
    for typ, count, estimates in expected_materials:
        for action, estimates_row in zip(("Reject", "Request supplementation", "Use"), estimates):
            row = next(r for r in materials if r["material_type"] == typ and r["action"] == action)
            check(typ + " AI count", int(row["ai_n"]), count)
            for field, expected in zip(("ai_percent", "other_percent", "conditional_or", "or_ci_lo", "or_ci_hi"), estimates_row):
                check(typ + " " + action + " " + field, row[field], expected, 2)
    fix = next(r for r in materials if r["material_type"] == "Proposed fix" and r["action"] == "Use")
    check("proposed fix Use q", fix["q_exact"], .0498, 4)
    usage = read("maintainer_usage.json")
    for field, expected in dict(replies=224979, ai_replies=2291, ai_reports=1573,
                                bot_only_reports=959, assist_only_reports=523, both_reports=91).items():
        check(field, usage[field], expected)
    check("maintainer accounts", usage["accounts"]["accounts"], 253)
    check("maintainer projects", usage["accounts"]["projects"], 82)
    trends = {r["period"]: r for r in table("maintainer_trends.csv")}
    for year, expected in [("2024", 61), ("2025", 251), ("2026", 1905)]:
        check(year + " AI replies", int(trends[year]["ai_replies"]), expected)
    for row in table("temporal_trends.csv"):
        if row["sample"] == "all" and row["specification"] == "project_role_FE" and row["metric"] in ("high", "valid_decided"):
            expected = 5.41 if row["metric"] == "high" else 4.89
            check(row["metric"] + " quarterly trend", row["estimate"], expected, 2)
    lengths = {r["group"]: r for r in table("report_length.csv")}
    for group, expected in [("AI-involved", 2573), ("Other", 1636), ("AI-discovered", 2853.5), ("AI-assisted", 2528.5)]:
        check(group + " median length", float(lengths[group]["median"]), expected)
    if failures:
        raise SystemExit("\n".join(failures) + f"\n{len(failures)} / {checks} checks failed")
    print(f"Passed {checks} result checks; input checksum matches this full run.")


if __name__ == "__main__":
    main()
