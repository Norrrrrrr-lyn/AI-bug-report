"""Project-quarter weighted differences with project-cluster bootstrap inference."""

import numpy as np
from scipy import stats

from .common import (ACTIONS, ACTION_KEYS, BUGZILLA, ELEMENTS, GROUPS, INVOLVED,
                     OTHER, REASONS, quarter, write_json)


def bh(ps):
    ps = np.asarray(ps, dtype=float)
    if not np.isfinite(ps).all():
        raise ValueError("Cannot correct non-finite p-values")
    order = np.argsort(ps)
    q = np.empty(len(ps))
    q[order] = np.minimum(1, np.minimum.accumulate(
        (ps[order] * len(ps) / np.arange(1, len(ps) + 1))[::-1])[::-1])
    return q


def bootstrap_draws(n_projects, n_boot=5000, seed=20260101):
    rng = np.random.default_rng(seed)
    # Preserve the study's draw construction and sorted project order.
    return np.stack([np.bincount(rng.integers(0, n_projects, n_projects), minlength=n_projects)
                     for _ in range(n_boot)])


def compare(df, measure, roles, projects, draws, scale=100, adjusted=True):
    data = df.dropna(subset=[measure])
    keys = ["project", "quarter"] if adjusted else ["project"]
    a = data[data.role.isin(roles)].groupby(keys)[measure].agg(["sum", "count"])
    b = data[data.role.isin(OTHER)].groupby(keys)[measure].agg(["sum", "count"])
    if adjusted:
        common = a.index.intersection(b.index)
        a, b = a.loc[common], b.loc[common]
        numerator = (a["sum"] - a["count"] * b["sum"] / b["count"]).groupby(level=0).sum().reindex(projects, fill_value=0).to_numpy()
        denominator = a["count"].groupby(level=0).sum().reindex(projects, fill_value=0).to_numpy()
        if denominator.sum() == 0:
            raise ValueError("No project-quarter stratum contains both groups")
        est = numerator.sum() / denominator.sum()
        den = draws @ denominator
        boot = (draws @ numerator)[den > 0] / den[den > 0]
        matched = dict(strata=len(common), ai_reports=int(a["count"].sum()), other_reports=int(b["count"].sum()))
    else:
        a, b = a.reindex(projects, fill_value=0), b.reindex(projects, fill_value=0)
        den_a, den_b = draws @ a["count"].to_numpy(), draws @ b["count"].to_numpy()
        keep = (den_a > 0) & (den_b > 0)
        boot = (draws @ a["sum"].to_numpy())[keep] / den_a[keep] - (draws @ b["sum"].to_numpy())[keep] / den_b[keep]
        est = a["sum"].sum() / a["count"].sum() - b["sum"].sum() / b["count"].sum()
        matched = {}
    est, boot = float(est * scale), boot * scale
    if len(boot) < 2:
        raise ValueError("Too few bootstrap draws with both groups")
    lo, hi = np.percentile(boot, [2.5, 97.5])
    se = float(boot.std(ddof=1))
    p = float(2 * stats.norm.sf(abs(est) / se)) if se else float(est == 0)
    return dict(est=est, lo=float(lo), hi=float(hi), se=se, p=p,
                bootstrap_valid=len(boot), **matched)


def family(df, measures, projects, draws, role_tests=True):
    groups = {}
    for name, roles in GROUPS.items():
        g = df[df.role.isin(roles)]
        groups[name] = dict(n=len(g), **{
            m: float(g[m].mean() * scale) for m, scale in measures.items()},
            denominators={m: int(g[m].notna().sum()) for m in measures})
    results = {"groups": groups, "matched": {}, "pooled": {}, "roles": {}}
    for kind in ("matched", "pooled"):
        result = results[kind]
        for m, scale in measures.items():
            result[m] = compare(df, m, INVOLVED, projects, draws, scale, kind == "matched")
        for m, q in zip(measures, bh([result[m]["p"] for m in measures])):
            result[m]["q"] = float(q)
    if role_tests:
        for role in INVOLVED:
            results["roles"][role] = {m: compare(df, m, [role], projects, draws, scale)
                                      for m, scale in measures.items()}
        keys = [(r, m) for r in INVOLVED for m in measures]
        for (r, m), q in zip(keys, bh([results["roles"][r][m]["p"] for r, m in keys])):
            results["roles"][r][m]["q"] = float(q)
    return results


def features(df):
    df = df.copy()
    df["quarter"] = df.month.map(quarter)
    for name, level in (("q_high", "high"), ("q_med", "medium"), ("q_low", "low")):
        df[name] = (df.quality == level).astype(int)
    for e in ELEMENTS:
        df["m_" + e] = df.missing.map(lambda values: int(e in values))
    df["n_missing"] = df.missing.map(len)
    for verdict in ("valid", "invalid", "uncertain"):
        df["v_" + verdict] = (df.verdict == verdict).astype(int)
    df["v_dec_valid"] = df.v_valid.where(df.verdict != "uncertain", np.nan)
    for day in (1, 7, 30, 90):
        df[f"c_{day}d"] = ((df.closure_day >= 0) & (df.closure_day <= day)).astype(int)
    df["c_ever"] = (df.closure_day >= 0).astype(int)
    for day in (1, 7, 30):
        df[f"r_{day}d"] = (df[f"replies_{day}d"] > 0).astype(int)
    df["r_3plus"] = (df.replies_30d >= 3).astype(int)
    df["n_replies"] = df.replies_30d
    for key in ACTION_KEYS:
        df["n_" + key] = df["action_" + key]
    for stage, keys in (("triage", ["info", "dup"]), ("validation", ["repro", "code"]),
                        ("resolution", ["fix", "patch"])):
        df["n_" + stage] = df[["n_" + k for k in keys]].sum(axis=1)
    df["n_all"] = df[["n_" + k for k in ACTION_KEYS]].sum(axis=1)
    df["b_bot"] = (df.ai_bot_replies > 0).astype(int)
    df["b_human"] = (df.ai_assist_replies > 0).astype(int)
    df["b_any"] = ((df.b_bot + df.b_human) > 0).astype(int)
    for i, stage in enumerate(("triage", "validation", "resolution")):
        names = set(ACTIONS[2 * i:2 * i + 2])
        df["b_" + stage] = df.ai_actions.map(lambda values: int(bool(names & values)))
    return df


def run(df, output, n_boot=5000):
    df = features(df)
    projects = sorted(df.project.unique())
    draws = bootstrap_draws(len(projects), n_boot)
    complete = {k: 100 for k in ["q_high", "q_med", "q_low"] + ["m_" + e for e in ELEMENTS]}
    complete["n_missing"] = 1
    write_json(output / "completeness.json", family(df, complete, projects, draws, role_tests=False))
    print("  completeness", flush=True)
    write_json(output / "validity.json", family(df, {k: 100 for k in ["v_valid", "v_invalid", "v_uncertain", "v_dec_valid"]}, projects, draws))
    rejected = df[df.verdict == "invalid"].copy()
    reason_keys = ["r_misuse", "r_expected", "r_unrepro", "r_incorrect", "r_scope", "r_others"]
    for key, reason in zip(reason_keys, REASONS):
        rejected[key] = rejected.reasons.map(lambda values: int(reason in values))
    write_json(output / "rejection_comparison.json",
               family(rejected, dict.fromkeys(reason_keys, 100), projects, draws))
    cohort = df[df.eligible90 == 1]
    write_json(output / "closure.json", family(cohort, {k: 100 for k in ["c_1d", "c_7d", "c_30d", "c_90d", "c_ever"]}, projects, draws))
    replies = {k: 100 for k in ["r_1d", "r_7d", "r_30d", "r_3plus"]}
    replies["n_replies"] = 1
    write_json(output / "replies.json", family(cohort, replies, projects, draws))
    print("  validity, closure, replies", flush=True)
    github = set(projects) - {BUGZILLA}
    actions = {"n_" + k: 1 for k in ACTION_KEYS + ["triage", "validation", "resolution", "all"]}
    # Actions retain the original bootstrap over all 101 projects, even though
    # Bugzilla contributes no action rows; the AI reply comparison draws 100.
    action_cohort = cohort[cohort.project.isin(github)]
    result = family(action_cohort, actions, projects, draws)
    for name, roles in GROUPS.items():
        g = action_cohort[action_cohort.role.isin(roles)]
        total = int(g.n_all.sum())
        result["groups"][name]["action_total"] = total
        result["groups"][name]["composition_percent"] = {k: float(100 * g[k].sum() / total) for k in actions if k != "n_all"}
    write_json(output / "actions.json", result)
    gh_df = df[df.project.isin(github)]
    gh_projects = sorted(gh_df.project.unique())
    gh_draws = bootstrap_draws(len(gh_projects), n_boot)
    write_json(output / "maintainer_comparison.json", family(gh_df, {k: 100 for k in ["b_any", "b_bot", "b_human", "b_triage", "b_validation", "b_resolution"]}, gh_projects, gh_draws))
    print("  actions, maintainer comparison", flush=True)
