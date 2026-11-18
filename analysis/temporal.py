"""Quarterly completeness/validity trends and the published sensitivity fits."""

import numpy as np
import pandas as pd
import statsmodels.api as sm

from .common import INVOLVED, write_csv
from .comparisons import bh

ROLES = ["assisted", "discovered", "suspected"]
MAIN = ["high", "missing", "valid", "invalid", "uncertain", "valid_decided"]

def subsets(df):
    yield ('AI-involved', df[df.group == 'AI-involved'])
    yield ('Other', df[df.group == 'Other'])
    for role in ROLES:
        yield (role, df[df.role == role])


def estimate(g, metric, repos, draws):
    d = g.dropna(subset=[metric])
    if d.empty:
        return dict(n=0, numerator=0, estimate=np.nan, lo=np.nan, hi=np.nan, bootstrap_valid=0)
    a = d.groupby('repo')[metric].agg(['sum', 'count']).reindex(repos, fill_value=0)
    den = draws @ a['count'].to_numpy(float)
    num = draws @ a['sum'].to_numpy(float)
    boot = np.divide(num, den, out=np.full(len(den), np.nan), where=den > 0)
    scale = 1 if metric == 'missing' else 100
    lo, hi = np.nanpercentile(boot, [2.5, 97.5]) * scale
    return dict(n=len(d), numerator=float(d[metric].sum()), estimate=d[metric].mean() * scale, lo=lo, hi=hi, bootstrap_valid=int(np.isfinite(boot).sum()))


def trends(df):
    """Exploratory linear trends; project-clustered normal Wald tests.
    LPM provides pp/quarter directly; no quality adjustment for validity because
    quality change is itself part of the temporal association under investigation.
    """
    result = []
    ai = df[df.group == 'AI-involved']
    for sample, g in [('all', ai), ('exclude_2026Q3', ai[ai.time < 10]), ('confirmed_AI_only', ai[ai.role != 'suspected'])]:
        for specification in ['unadjusted', 'project_FE', 'project_role_FE']:
            for m in MAIN:
                d = g.dropna(subset=[m]).copy()
                cols = [] if specification == 'unadjusted' else ['repo']
                if specification == 'project_role_FE':
                    cols += ['role']
                x = d[['time']].astype(float)
                if cols:
                    x = pd.concat([x, pd.get_dummies(d[cols], drop_first=True, dtype=float)], axis=1)
                x = sm.add_constant(x)
                fit = sm.OLS(d[m], x).fit(cov_type='cluster', cov_kwds={'groups': d.repo, 'use_correction': True}, use_t=False)
                scale = 1 if m == 'missing' else 100
                ci = fit.conf_int().loc['time'] * scale
                result.append(dict(sample=sample, specification=specification, metric=m, n=len(d), projects=d.repo.nunique(), estimate=fit.params['time'] * scale, se=fit.bse['time'] * scale, lo=ci.iloc[0], hi=ci.iloc[1], p=fit.pvalues['time'], unit='elements/quarter' if m == 'missing' else 'pp/quarter'))
    out = pd.DataFrame(result)
    out['q'] = out.groupby(['sample', 'specification'])['p'].transform(lambda s: bh(s.to_numpy()))
    return out


def run(reports, output, n_boot=5000):
    df = reports[["project", "month", "role", "quality", "verdict", "missing"]].copy()
    df = df.rename(columns={"project": "repo"})
    df["year"] = df.month.str[:4]
    df["time"] = (df.year.astype(int) - 2024) * 4 + (df.month.str[5:7].astype(int) - 1) // 3
    df["quarter"] = df.year + "Q" + ((df.time % 4) + 1).astype(str)
    df["group"] = np.where(df.role.isin(INVOLVED), "AI-involved", "Other")
    df["high"] = (df.quality == "high").astype(int)
    df["missing"] = df.missing.map(len)
    for name in ("valid", "invalid", "uncertain"):
        df[name] = (df.verdict == name).astype(int)
    df["valid_decided"] = df.valid.where(df.verdict != "uncertain", np.nan)
    projects = sorted(df.repo.unique())
    rng = np.random.default_rng(20261106)
    draws = rng.multinomial(len(projects), np.full(len(projects), 1 / len(projects)), size=n_boot).astype(float)
    rows = []
    for frequency in ("quarter", "year"):
        for name, g in subsets(df):
            for period, sub in g.groupby(frequency):
                for metric in MAIN:
                    rows.append(dict(frequency=frequency, period=period, group=name, metric=metric,
                                     **estimate(sub, metric, projects, draws)))
    write_csv(output / "temporal_rates.csv", rows)
    trends(df).to_csv(output / "temporal_trends.csv", index=False)
