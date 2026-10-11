import random
from datetime import datetime, timedelta, timezone

from dailyenglish.planner import (MAX_PER_TAG, MIN_GRAMMAR, MIN_VOCAB, READING_QUESTIONS,
                                  USAGE_COUNT, Skill, SkillStat, build_plan, expected_correct,
                                  tag_weight)

SKILLS = (
    [Skill(f"grammar:g{i}", "usage", f"g{i}") for i in range(6)]
    + [Skill(f"vocab:v{i}", "usage", f"v{i}") for i in range(4)]
    + [Skill(f"reading:r{i}", "reading", f"r{i}") for i in range(6)]
)
NOW = datetime(2026, 10, 11, tzinfo=timezone.utc)


def test_plan_shape():
    for seed in range(50):
        plan = build_plan(SKILLS, {}, 805, 900, 0, random.Random(seed), NOW)
        tags = [s.skill_tag for s in plan.usage]
        assert len(tags) == USAGE_COUNT
        assert sum(t.startswith("grammar:") for t in tags) >= MIN_GRAMMAR
        assert sum(t.startswith("vocab:") for t in tags) >= MIN_VOCAB
        assert max(tags.count(t) for t in tags) <= MAX_PER_TAG
        assert len(plan.reading.slots) == READING_QUESTIONS
        assert len({s.skill_tag for s in plan.reading.slots}) == READING_QUESTIONS
        slots = [s.slot for s in plan.usage + plan.reading.slots]
        assert slots == list(range(len(slots)))
        for s in plan.usage + plan.reading.slots:
            assert 400 <= s.target_level <= 980
            assert s.exam_style in ("toeic", "flpt")


def test_weak_and_stale_tags_weigh_more():
    strong = SkillStat(920, 40, NOW)
    weak = SkillStat(720, 40, NOW)
    stale = SkillStat(920, 40, NOW - timedelta(days=30))
    stats = {"a": strong, "b": weak, "c": stale}
    assert tag_weight("b", stats, 805, 900, NOW) > tag_weight("a", stats, 805, 900, NOW)
    assert tag_weight("c", stats, 805, 900, NOW) > tag_weight("a", stats, 805, 900, NOW)
    assert tag_weight("new", stats, 805, 900, NOW) > tag_weight("a", stats, 805, 900, NOW)


def test_weak_tag_is_picked_more_often():
    stats = {s.tag: SkillStat(930, 50, NOW) for s in SKILLS}
    stats["grammar:g0"] = SkillStat(650, 50, NOW)
    hits = 0
    for seed in range(200):
        plan = build_plan(SKILLS, stats, 805, 900, 500, random.Random(seed), NOW)
        hits += sum(s.skill_tag == "grammar:g0" for s in plan.usage)
    assert hits / 200 > 1.0  # 平均每天超過一題


def test_difficulty_tracks_rating():
    stats = {s.tag: SkillStat(700, 50, NOW) for s in SKILLS}
    levels = []
    for seed in range(100):
        plan = build_plan(SKILLS, stats, 805, 900, 500, random.Random(seed), NOW)
        levels += [s.target_level for s in plan.usage]
    mean = sum(levels) / len(levels)
    assert 690 < mean < 740


def test_expected_correct():
    assert abs(expected_correct(800, 800) - 0.625) < 1e-9
    assert expected_correct(600, 900) > 0.95
    assert 0.25 < expected_correct(990, 500) < 0.27
