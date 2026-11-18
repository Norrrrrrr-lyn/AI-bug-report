"""AI adoption, discovery, tasks, report lengths, and maintainer interactions."""

import numpy as np

from .common import (ACTIONS, BUGZILLA, GROUPS, INVOLVED, ORIGINS, REASONS,
                     TASKS, write_csv, write_json)


def cooccurrence(values, vocabulary):
    membership = np.array([[name in row for name in vocabulary] for row in values], dtype=int)
    matrix = membership.T @ membership
    return {a: {b: int(matrix[i, j]) for j, b in enumerate(vocabulary)} for i, a in enumerate(vocabulary)}


def run(df, replies, output):
    projects = df[["project", "language"]].drop_duplicates()
    languages = {}
    for language, g in df.groupby("language"):
        languages[language] = dict(reports=len(g), ai_reports=int(g.role.isin(INVOLVED).sum()))
    write_json(output / "profile.json", dict(
        projects=len(projects), reports=len(df), github_reports=int((df.project != BUGZILLA).sum()),
        followup_comments=int(df.followup_comments.sum()),
        roles={k: int(v) for k, v in df.role.value_counts().items()},
        languages={k: int(v) for k, v in projects.language.value_counts().items()},
        report_languages=languages,
    ))
    periods = {m: g for m, g in df.groupby("month")}
    periods.update({y: df[df.month.str.startswith(y)] for y in ("2024", "2025", "2026")})
    periods["2026Q3"] = df[df.month >= "2026-07"]
    periods["all"] = df
    scale = []
    for period, g in periods.items():
        counts = g.role.value_counts()
        ai = g[g.role.isin(INVOLVED)]
        scale.append(dict(period=period, reports=len(g), ai_reports=len(ai), ai_percent=100 * len(ai) / len(g),
            **{r: int(counts.get(r, 0)) for r in INVOLVED}, distinct_accounts=int(ai.reporter.nunique()),
            projects=int(ai.project.nunique()), top5_project_percent=float(100 * ai.project.value_counts().head(5).sum() / len(ai))))
    write_csv(output / "adoption.csv", scale)

    origin = {}
    for name, roles in GROUPS.items():
        g = df[df.role.isin(roles)]
        origin[name] = dict(n=len(g), counts={o: int((g.origin == o).sum()) for o in ORIGINS},
                            percent={o: float(100 * (g.origin == o).mean()) for o in ORIGINS})
    write_json(output / "discovery.json", origin)
    assisted = df[df.role == "assisted"]
    tasked = assisted[assisted.tasks.map(bool)]
    counts = tasked.tasks.map(len).value_counts().sort_index()
    write_json(output / "tasks.json", dict(assisted=len(assisted), with_task=len(tasked),
        counts={t: int(tasked.tasks.map(lambda values: t in values).sum()) for t in TASKS},
        tasks_per_report={str(k): int(v) for k, v in counts.items()},
        two_or_more=int((tasked.tasks.map(len) >= 2).sum()), cooccurrence=cooccurrence(tasked.tasks, TASKS)))

    rejected = df[df.verdict == "invalid"]
    other = rejected[~rejected.role.isin(INVOLVED)]
    reasons = []
    for name, roles in GROUPS.items():
        g = rejected[rejected.role.isin(roles)]
        for reason in REASONS:
            count = int(g.reasons.map(lambda values: reason in values).sum())
            percent = 100 * count / len(g)
            baseline = 100 * other.reasons.map(lambda values: reason in values).mean()
            reasons.append(dict(group=name, reason=reason, invalid_reports=len(g), count=count,
                                percent=percent, observed_difference_pp=float(percent - baseline)))
    write_csv(output / "rejection_reasons.csv", reasons)

    lengths, survival, closure = [], [], []
    cohort = df[df.eligible90 == 1]
    for name, roles in GROUPS.items():
        v = df.loc[df.role.isin(roles), "characters"]
        lengths.append(dict(group=name, n=len(v), mean=float(v.mean()), median=float(v.median()),
            p25=float(v.quantile(.25)), p75=float(v.quantile(.75)), min=int(v.min()), max=int(v.max())))
        g = cohort[cohort.role.isin(roles)]
        for k in range(max(10, int(g.replies_30d.max())) + 2):
            survival.append(dict(group=name, minimum_replies=k, n=len(g),
                                 percent=float(100 * (g.replies_30d >= k).mean())))
        for day in range(91):
            closure.append(dict(group=name, day=day, n=len(g),
                                percent=float(100 * ((g.closure_day >= 0) & (g.closure_day <= day)).mean())))
    write_csv(output / "report_length.csv", lengths)
    write_csv(output / "reply_survival.csv", survival)
    write_csv(output / "closure_daily.csv", closure)
    discovered_closed = cohort[(cohort.role == "discovered") & (cohort.closure_day >= 0) & (cohort.closure_day <= 90)]
    uncertain = discovered_closed[discovered_closed.verdict == "uncertain"]
    write_json(output / "closure_verdict.json", dict(discovered_closed90=len(discovered_closed),
        uncertain=len(uncertain), uncertain_without_followup=int((uncertain.followup_comments == 0).sum())))

    ai = replies[replies.role != "no_ai"]
    ai_reports = df[(df.ai_bot_replies + df.ai_assist_replies) > 0]
    total_actions = ai.actions.map(len).sum()
    actions = {}
    for name in ACTIONS:
        all_count = replies.actions.map(lambda values: name in values).sum()
        a = ai[ai.actions.map(lambda values: name in values)]
        actions[name] = dict(all_replies=int(all_count), ai_replies=len(a),
            bot_replies=int((a.role == "ai_bot").sum()), assist_replies=int((a.role == "ai_assist").sum()),
            percent_of_ai_actions=float(100 * len(a) / total_actions),
            ai_share_of_action_replies=float(100 * len(a) / all_count))
    stage_share = {stage: float(100 * sum(actions[name]["ai_replies"] for name in ACTIONS[2*i:2*i+2]) / total_actions)
                   for i, stage in enumerate(("Triage", "Validation", "Resolution"))}
    write_json(output / "maintainer_usage.json", dict(replies=len(replies), ai_replies=len(ai), ai_reports=len(ai_reports),
        bot_replies=int((ai.role == "ai_bot").sum()), assist_replies=int((ai.role == "ai_assist").sum()),
        bot_only_reports=int(((ai_reports.ai_bot_replies > 0) & (ai_reports.ai_assist_replies == 0)).sum()),
        assist_only_reports=int(((ai_reports.ai_bot_replies == 0) & (ai_reports.ai_assist_replies > 0)).sum()),
        both_reports=int(((ai_reports.ai_bot_replies > 0) & (ai_reports.ai_assist_replies > 0)).sum()),
        accounts=dict(accounts=int(ai.account.nunique()), projects=int(ai.project.nunique())),
        actions=actions, stage_share_percent=stage_share,
        reports_with_actions=int(df.ai_actions.map(bool).sum()),
        reports_with_multiple_actions=int((df.ai_actions.map(len) >= 2).sum()),
        cooccurrence=cooccurrence(df.ai_actions, ACTIONS)))

    # The reply totals above include the snapshot tail; trends use complete months.
    calendar = replies[(replies.month >= "2024-01") & (replies.month < "2026-10")]
    period_data = {m: g for m, g in calendar.groupby("month")}
    period_data.update({y: g for y, g in calendar.groupby(calendar.month.str[:4])})
    trends = []
    for period, g in period_data.items():
        ai = g[g.role != "no_ai"]
        trends.append(dict(period=period, replies=len(g), ai_replies=len(ai), ai_percent=100 * len(ai) / len(g),
            ai_bot=int((ai.role == "ai_bot").sum()), ai_assist=int((ai.role == "ai_assist").sum()),
            accounts=int(ai.account.nunique()), projects=int(ai.project.nunique()),
            top5_project_percent=float(100 * ai.project.value_counts().head(5).sum() / len(ai)) if len(ai) else 0.))
    write_csv(output / "maintainer_trends.csv", trends)
