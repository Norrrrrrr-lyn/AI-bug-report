"""Firth logistic regression with project-clustered covariance, as in the study.

Only the two published models are fitted. Model A uses quality; Model B replaces
quality with missing elements. AI-role and project/quarter terms are controls.
"""

import math
import numpy as np
from scipy import stats
from scipy.linalg import cho_factor, cho_solve

from .common import ELEMENTS, TASKS, quarter, write_json
from .comparisons import bh

ORIGINS = ["Build / Installation", "Dynamic Analysis", "Fuzzing", "Source Code Review",
           "Static Analysis", "Testing", "Unknown"]
ROLES = ["discovered", "assisted", "suspected"]

def _parts(x, beta):
    mu = 1 / (1 + np.exp(-np.clip(x @ beta, -30, 30)))
    w = np.maximum(mu * (1 - mu), 1e-12)
    xw = x * np.sqrt(w)[:, None]
    a = xw.T @ xw
    c = cho_factor(a)
    z = cho_solve(c, xw.T)
    h = np.einsum('ij,ji->i', xw, z)
    logdet = 2 * np.log(np.diag(c[0])).sum()
    return (mu, w, a, c, h, logdet)


def fit_firth(y, x, tol=1e-08, max_iter=100):
    beta = np.zeros(x.shape[1])
    beta[0] = math.log((y.sum() + 0.5) / (len(y) - y.sum() + 0.5))

    def pen_ll(b):
        mu, _, _, _, _, logdet = _parts(x, b)
        return float((y * np.log(mu) + (1 - y) * np.log(1 - mu)).sum() + 0.5 * logdet)
    cur = pen_ll(beta)
    for it in range(max_iter):
        mu, w, a, c, h, _ = _parts(x, beta)
        step = cho_solve(c, x.T @ (y - mu + h * (0.5 - mu)))
        mx = np.abs(step).max()
        if mx > 5:
            step *= 5 / mx
        t = 1.0
        while t > 1e-06:
            new = pen_ll(beta + t * step)
            if new >= cur - 1e-10:
                break
            t /= 2
        beta = beta + t * step
        delta = abs(new - cur)
        cur = new
        if np.abs(t * step).max() < tol and delta < 1e-09:
            break
    mu, w, a, c, h, _ = _parts(x, beta)
    return {'beta': beta, 'mu': mu, 'h': h, 'A': a, 'pen_ll': cur, 'iters': it + 1}


def cluster_cov(fit, x, y, groups):
    resid = y - fit['mu'] + fit['h'] * (0.5 - fit['mu'])
    u = x * resid[:, None]
    ug = np.zeros((groups.max() + 1, x.shape[1]))
    np.add.at(ug, groups, u)
    meat = ug.T @ ug
    g = len(np.unique(groups))
    a_inv = np.linalg.inv(fit['A'])
    return g / (g - 1) * a_inv @ meat @ a_inv


def fe_columns(rows):
    cols, x = ([], [])
    for key, tag in (('repo', 'project'), ('quarter', 'quarter')):
        levels = sorted({r[key] for r in rows})
        for lv in levels[1:]:
            cols.append(f'{tag}[{lv}]')
            x.append([r[key] == lv for r in rows])
    return (cols, x)


def build(rows, blocks):
    """blocks: list of (block name, [(term name, rule)], exclusive). Terms with no variation are dropped."""
    cols, x, meta = (['intercept'], [np.ones(len(rows))], [])
    for name, terms, exclusive in blocks:
        idx = []
        for tname, rule in terms:
            v = np.array([bool(rule(r)) for r in rows], float)
            if v.sum() == 0 or v.sum() == len(v):
                continue
            cols.append(tname)
            x.append(v)
            idx.append(len(cols) - 1)
        meta.append({'block': name, 'idx': idx, 'exclusive': exclusive})
    nonfe = len(cols)
    fc, fx = fe_columns(rows)
    for c, v in zip(fc, fx):
        arr = np.array(v, float)
        if 0 < arr.sum() < len(arr):
            cols.append(c)
            x.append(arr)
    return (np.column_stack(x), cols, meta, nonfe)


def role_block():
    return ('AI role', [(f'role[{lv}]', lambda r, lv=lv: r['ai'] == lv) for lv in ROLES], False)


def origin_block():
    return ('Discovery method', [(f'origin[{o}]', lambda r, o=o: r['origin'] == o) for o in ORIGINS], True)


def task_block(assisted_only=True):
    return ('AI task', [(f'task[{t}]', lambda r, t=t: t in r['tasks'] and (r['ai'] == 'assisted' or not assisted_only)) for t in TASKS], False)


def quality_block():
    return ('Report quality', [(f'quality[{q}]', lambda r, q=q: r['quality'] == q) for q in ('low', 'high')], True)


def missing_block(elements=ELEMENTS):
    return ('Missing element', [(f'missing[{e}]', lambda r, e=e: e in r['miss']) for e in elements], False)


def fit(rows, blocks):
    y = np.array([r["valid"] for r in rows], float)
    projects = sorted({r["repo"] for r in rows})
    index = {p: i for i, p in enumerate(projects)}
    groups = np.array([index[r["repo"]] for r in rows])
    x, columns, meta, _ = build(rows, blocks)
    fitted = fit_firth(y, x)
    covariance = cluster_cov(fitted, x, y, groups)
    beta = fitted["beta"]
    se = np.sqrt(np.diag(covariance))
    result = dict(n=len(rows), valid=int(y.sum()), projects=len(projects),
                  iterations=fitted["iters"], coefs={}, tests={})
    for block in meta:
        for j in block["idx"]:
            result["coefs"][columns[j]] = dict(
                **{"or": math.exp(beta[j])}, lo=math.exp(beta[j] - 1.96 * se[j]),
                hi=math.exp(beta[j] + 1.96 * se[j]), p=float(2 * stats.norm.sf(abs(beta[j] / se[j]))),
                n=int(x[:, j].sum()), valid_pct=float(100 * y[x[:, j] == 1].mean()))
        indices = block["idx"]
        b = beta[indices]
        wald = float(b @ np.linalg.solve(covariance[np.ix_(indices, indices)], b))
        result["tests"][block["block"]] = dict(df=len(indices), wald=wald,
            p=float(stats.chi2.sf(wald, len(indices))))
    # Expose convergence diagnostics instead of silently accepting an iteration cap.
    score = x.T @ (y - fitted["mu"] + fitted["h"] * (.5 - fitted["mu"]))
    result["max_abs_adjusted_score"] = float(np.abs(score).max())
    if result["max_abs_adjusted_score"] > 1e-4:
        raise RuntimeError("Firth fit did not converge sufficiently")
    return result


def run(df, output):
    rows = [dict(repo=r["project"], quarter=quarter(r["month"]), valid=int(r["verdict"] == "valid"),
                 ai=r["role"], quality=r["quality"], origin=r["origin"],
                 tasks=set(r["tasks"]), miss=set(r["missing"]))
            for r in df.to_dict("records") if r["verdict"] != "uncertain"]
    print(f"  fitting Model A on {len(rows):,} decided reports", flush=True)
    a = fit(rows, [origin_block(), task_block(), quality_block(), role_block()])
    print("  fitting Model B", flush=True)
    b = fit(rows, [missing_block(), origin_block(), task_block(), role_block()])
    result = {"A": a, "B": b}
    shown = [("A", k) for k in a["coefs"] if not k.startswith("role[")]
    shown += [("B", k) for k in b["coefs"] if k.startswith("missing[")]
    for (model, key), q in zip(shown, bh([result[m]["coefs"][k]["p"] for m, k in shown])):
        result[model]["coefs"][key]["q"] = float(q)
    blocks = [("A", k) for k in a["tests"] if k != "AI role"] + [("B", "Missing element")]
    for (model, key), q in zip(blocks, bh([result[m]["tests"][k]["p"] for m, k in blocks])):
        result[model]["tests"][key]["q"] = float(q)
    write_json(output / "regression.json", result)
