from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.models import Character, Draft, Job
from app.services import schedule

from .conftest import OWNER, ready_character

NY = ZoneInfo("America/New_York")


def ms(*a, tz=NY) -> int:
    return int(datetime(*a, tzinfo=tz).timestamp() * 1000)


def test_slots_wall_clock_across_dst():
    sc = {"times": ["18:00", "09:30"], "days": [0, 1, 2, 3, 4, 5, 6], "tz": "America/New_York"}
    # DST ends in New York on 2026-11-01
    got = schedule.slots(sc, ms(2026, 10, 31, 12), ms(2026, 11, 2, 0))
    assert [datetime.fromtimestamp(x / 1000, NY).strftime("%m-%d %H:%M") for x in got] == \
        ["10-31 18:00", "11-01 09:30", "11-01 18:00"]
    assert got[2] - got[0] == 25 * 3600_000  # the clock went back an hour, 18:00 stays 18:00


def test_slots_days_filter_and_bad_input():
    sc = {"times": ["18:00", "bad"], "days": [4], "tz": "Nowhere/Invalid"}  # Fridays, falls back to UTC
    got = schedule.slots(sc, ms(2026, 11, 2, 0, tz=ZoneInfo("UTC")), ms(2026, 11, 16, 0, tz=ZoneInfo("UTC")))
    assert [datetime.fromtimestamp(x / 1000, ZoneInfo("UTC")).strftime("%a %H:%M") for x in got] == \
        ["Fri 18:00", "Fri 18:00"]


def test_rubric_of_the_day():
    ch = Character(schedule={"tz": "America/New_York"}, rubrics=[
        {"weekday": 0, "title": "Monday sit-downs"}, {"weekday": None, "title": "A"}, {"weekday": None, "title": "B"}])
    assert schedule.rubric_for(ch, ms(2026, 11, 9, 18))["title"] == "Monday sit-downs"
    tue, wed = schedule.rubric_for(ch, ms(2026, 11, 10, 18)), schedule.rubric_for(ch, ms(2026, 11, 11, 18))
    assert {tue["title"], wed["title"]} == {"A", "B"}


async def test_planner_is_idempotent(client, ctx):
    ch = await ready_character(client, ctx, OWNER)
    async with ctx.db.sessions() as s:
        c = await s.get(Character, ch["id"])
        c.schedule = {"times": ["09:00", "18:00"], "days": list(range(7)), "tz": "America/New_York", "lead_hours": 24}
        await s.commit()
    now = ms(2026, 11, 9, 8)  # Monday 08:00 in New York
    assert await schedule.plan(ctx, now) == 2  # today 09:00 and 18:00
    assert await schedule.plan(ctx, now) == 0
    later = now + 3600_000 + 60_000  # 09:01: the 24 h window now reaches Tuesday 09:00
    assert await schedule.plan(ctx, later) == 1
    assert await schedule.plan(ctx, later) == 0
    async with ctx.db.sessions() as s:
        drafts = (await s.execute(select(Draft).order_by(Draft.slot_ms))).scalars().all()
        jobs = (await s.execute(select(func.count()).select_from(Job).where(Job.kind == "plan"))).scalar_one()
    assert len(drafts) == 3 and jobs == 3
    assert drafts[0].rubric == "Monday sit-downs"  # Don Whiskers' Monday rubric


async def test_planner_skips_not_ready_and_archived(client, ctx):
    ch = await ready_character(client, ctx, OWNER)
    await client.post("/api/characters/from-template/tilted", headers={"Authorization": f"tma dev:{OWNER}"})
    await client.delete(f"/api/characters/{ch['id']}", headers={"Authorization": f"tma dev:{OWNER}"})
    assert await schedule.plan(ctx, ms(2026, 11, 9, 13)) == 0
