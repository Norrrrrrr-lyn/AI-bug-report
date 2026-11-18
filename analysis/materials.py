"""Quarter-stratified exact conditional inference for exclusive material actions."""

import numpy as np
from scipy.optimize import brentq
from scipy.special import logsumexp
from scipy.stats import hypergeom

from .common import write_csv
from .comparisons import bh


def exact_test(tables):
    """Convolve hypergeometric distributions and invert conditional tail tests.

    Each table is (AI yes, AI no, Other yes, Other no). The two-sided p-value
    sums null probabilities no larger than the observed probability. The OR
    maximizes the conditional likelihood; its CI inverts equal-tailed tests.
    """
    pmf, offset, observed, informative = np.array([1.]), 0, 0, 0
    for a, b, c, d in tables:
        n, total, successes = a + b, a + b + c + d, a + c
        lo, hi = max(0, n - (total - successes)), min(n, successes)
        support = np.arange(lo, hi + 1)
        logp = hypergeom.logpmf(support, total, successes, n)
        pmf = np.convolve(pmf, np.exp(logp - logsumexp(logp)))
        pmf /= pmf.sum()
        offset += lo
        observed += a
        informative += hi > lo
    if len(pmf) == 1:
        raise ValueError("Material test has no conditional variation")
    support = np.arange(offset, offset + len(pmf))
    probability = pmf[observed - offset]
    p = float(min(1, pmf[pmf <= probability * (1 + 1e-7)].sum()))
    logp = np.log(pmf, where=pmf > 0, out=np.full_like(pmf, -np.inf))

    def tilted(log_odds):
        value = logp + support * log_odds
        return np.exp(value - logsumexp(value))

    def solve(function):
        return float(np.exp(brentq(function, -700, 700, xtol=1e-11)))

    odds = 0. if observed == support[0] else np.inf if observed == support[-1] else solve(lambda z: support @ tilted(z) - observed)
    lo = 0. if observed == support[0] else solve(lambda z: tilted(z)[support >= observed].sum() - .025)
    hi = np.inf if observed == support[-1] else solve(lambda z: tilted(z)[support <= observed].sum() - .025)
    return dict(p_exact=p, conditional_or=odds, or_ci_lo=lo, or_ci_hi=hi, informative_quarters=int(informative))


def run(rows, output):
    results, strata = [], []
    for typ in ("Reproducer", "Technical claim", "Proposed fix"):
        sub = [r for r in rows if r["material_type"] == typ]
        for action in ("Reject", "Request supplementation", "Use"):
            totals, yes = {}, {}
            for group in ("AI-generated", "Other"):
                totals[group] = sum(r["count"] for r in sub if r["origin"] == group)
                yes[group] = sum(r["count"] for r in sub if r["origin"] == group and r["action"] == action)
            tables = []
            for q in sorted({r["quarter"] for r in sub}):
                table = []
                for group in ("AI-generated", "Other"):
                    g = [r for r in sub if r["quarter"] == q and r["origin"] == group]
                    n = sum(r["count"] for r in g)
                    k = sum(r["count"] for r in g if r["action"] == action)
                    table.extend([k, n - k])
                if sum(table[:2]) and sum(table[2:]):
                    tables.append(table)
                    strata.append(dict(material_type=typ, action=action, quarter=q,
                                       **dict(zip(("ai_yes", "ai_no", "other_yes", "other_no"), table))))
            results.append(dict(material_type=typ, action=action, ai_n=totals["AI-generated"],
                ai_yes=yes["AI-generated"], other_n=totals["Other"], other_yes=yes["Other"],
                ai_percent=100 * yes["AI-generated"] / totals["AI-generated"],
                other_percent=100 * yes["Other"] / totals["Other"], **exact_test(tables)))
    for result, q in zip(results, bh([r["p_exact"] for r in results])):
        result["q_exact"] = float(q)
    write_csv(output / "materials.csv", results)
    write_csv(output / "material_strata.csv", strata)
