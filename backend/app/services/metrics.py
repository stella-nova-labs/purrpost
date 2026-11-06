"""Collecting metrics (24 h and 7 days after a post) and the dashboard numbers."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Account, AccountStat, Character, Draft, Metric, Publication, Usage
from ..publishers.base import PublishError
from .budget import month_start_ms
from .publishing import creds
from .users import now_ms

log = logging.getLogger("purrpost.metrics")

WINDOWS = {"24h": 86_400_000, "7d": 7 * 86_400_000}
FIELDS = ("likes", "comments", "reach", "saves", "views")


def _int(v):
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


async def collect(ctx, now: int | None = None) -> int:
    """Worker step. Each (publication, window) is fetched once; a failed fetch is retried next tick, and after
    a day it's recorded empty so it doesn't loop forever."""
    now = now or now_ms()
    n = 0
    async with ctx.db.sessions() as s:
        for kind, age in WINDOWS.items():
            have = select(Metric.publication_id).where(Metric.kind == kind)
            rows = (await s.execute(select(Publication).where(
                Publication.status == "published", Publication.published_ms <= now - age,
                Publication.id.not_in(have)).limit(50))).scalars().all()
            for p in rows:
                a = await s.get(Account, p.account_id)
                pub = ctx.publishers.get(p.platform)
                data: dict = {}
                try:
                    if a is not None and pub is not None and a.status == "ok":
                        data = await pub.metrics(creds(ctx, a), p.external_id)
                except PublishError as e:
                    if now - (p.published_ms + age) < 86_400_000:
                        log.info("metrics %s %s later: %s", p.id, kind, e.code)
                        continue
                    data = {"error": e.code}
                try:
                    async with s.begin_nested():
                        s.add(Metric(publication_id=p.id, kind=kind, fetched_ms=now, data=data,
                                     **{f: _int(data.get(f)) for f in FIELDS}))
                    n += 1
                except IntegrityError:
                    pass
        await s.commit()
    return n


async def account_stats(ctx, now: int | None = None) -> int:
    """Worker step: followers once a day per account."""
    now = now or now_ms()
    day = datetime.fromtimestamp(now / 1000, timezone.utc).strftime("%Y-%m-%d")
    n = 0
    async with ctx.db.sessions() as s:
        done = select(AccountStat.account_id).where(AccountStat.day == day)
        rows = (await s.execute(select(Account).where(Account.status == "ok", Account.id.not_in(done)))).scalars().all()
        for a in rows:
            pub = ctx.publishers.get(a.platform)
            try:
                st = await pub.account_stats(creds(ctx, a)) if pub else {}
            except PublishError:
                continue
            except Exception:  # noqa: BLE001 - Telegram errors etc.: try again tomorrow
                log.exception("account stats %s", a.id)
                st = {}
            try:
                async with s.begin_nested():
                    s.add(AccountStat(account_id=a.id, day=day, followers=_int(st.get("followers")), fetched_ms=now))
                n += 1
            except IntegrityError:
                pass
        await s.commit()
    return n


async def dashboard(ctx, s: AsyncSession, user_id: int, character_id: int | None) -> dict:
    q = select(Character).where(Character.user_id == user_id, Character.archived.is_(False))
    if character_id:
        q = q.where(Character.id == character_id)
    chars = list((await s.execute(q.order_by(Character.id))).scalars())
    ids = [c.id for c in chars]
    month = month_start_ms(ctx.settings)

    # posts with their best-known metrics (7 d beats 24 h)
    drafts = list((await s.execute(select(Draft).where(Draft.character_id.in_(ids), Draft.status.in_(
        ("published", "partially_published"))).order_by(Draft.published_ms.desc()).limit(60))).scalars())
    pubs = list((await s.execute(select(Publication).where(Publication.draft_id.in_([d.id for d in drafts])))).scalars())
    mets = list((await s.execute(select(Metric).where(Metric.publication_id.in_([p.id for p in pubs])))).scalars())
    best: dict[int, Metric] = {}
    for m in sorted(mets, key=lambda m: m.kind == "7d"):
        best[m.publication_id] = m
    by_draft: dict[int, dict] = defaultdict(lambda: {f: 0 for f in FIELDS} | {"platforms": {}, "has": False})
    for p in pubs:
        e = by_draft[p.draft_id]
        e["platforms"][p.platform] = p.permalink
        m = best.get(p.id)
        if m:
            e["has"] = True
            e["window"] = m.kind
            for f in FIELDS:
                e[f] += getattr(m, f) or 0
    names = {c.id: c.name for c in chars}
    posts = []
    for d in drafts:
        e = by_draft[d.id]
        first = d.slides[0]["key"] if d.slides else None
        posts.append({"id": d.id, "character": names.get(d.character_id), "character_id": d.character_id,
                      "published_ms": d.published_ms, "rubric": d.rubric, "idea": d.idea,
                      "thumb": ctx.storage.url(first) if first else None, "platforms": e["platforms"],
                      "metrics": {f: e[f] for f in FIELDS} if e["has"] else None, "window": e.get("window")})

    rub: dict[str, list] = defaultdict(list)
    for p in posts:
        if p["metrics"]:
            rub[p["rubric"] or ""].append(p["metrics"])
    rubrics = sorted(({"rubric": r, "posts": len(v), "avg_reach": round(sum(x["reach"] for x in v) / len(v)),
                       "avg_likes": round(sum(x["likes"] for x in v) / len(v))} for r, v in rub.items()),
                     key=lambda x: (x["avg_reach"], x["avg_likes"]), reverse=True)

    # followers: latest per account + daily series (sum over the character's accounts)
    accs = list((await s.execute(select(Account).where(Account.character_id.in_(ids)))).scalars())
    stats = list((await s.execute(select(AccountStat).where(AccountStat.account_id.in_([a.id for a in accs]))
                                  .order_by(AccountStat.day))).scalars())
    series: dict[str, int] = defaultdict(int)
    latest: dict[int, int] = {}
    for st in stats:
        if st.followers is not None:
            series[st.day] += st.followers
            latest[st.account_id] = st.followers
    platform_of = {a.id: a.platform for a in accs}
    followers = {pl: sum(v for aid, v in latest.items() if platform_of[aid] == pl)
                 for pl in sorted(set(platform_of.values())) if any(platform_of[aid] == pl for aid in latest)}

    spend = dict((await s.execute(select(Usage.character_id, func.sum(Usage.cost_usd)).where(
        Usage.user_id == user_id, Usage.created_ms >= month).group_by(Usage.character_id))).all())
    measured = [p["metrics"] for p in posts if p["metrics"]]
    month_posts = sum(1 for p in posts if (p["published_ms"] or 0) >= month)
    return {
        "characters": [{"id": c.id, "name": c.name, "autopilot": c.autopilot, "approved_streak": c.approved_streak,
                        "spend_month": round(spend.get(c.id, 0.0), 2)} for c in chars],
        "totals": {
            "followers": followers, "posts_month": month_posts, "posts": len(posts),
            "avg_reach": round(sum(m["reach"] for m in measured) / len(measured)) if measured else None,
            "avg_likes": round(sum(m["likes"] for m in measured) / len(measured)) if measured else None,
            "spend_month": round(sum(v for k, v in spend.items() if k in ids or (not character_id and k is None)), 2),
        },
        "followers_series": [{"day": k, "followers": v} for k, v in sorted(series.items())][-60:],
        "posts": posts, "rubrics": rubrics[:5],
    }
