"""決定今天要出哪些題目：技能、難度、考試風格。純函式，方便測試。"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

# v1（尚無聽力）每日題量：約 15 分鐘
USAGE_COUNT = 10
READING_QUESTIONS = 4
REVIEW_MAX = 3
MIN_GRAMMAR = 3
MIN_VOCAB = 3
MAX_PER_TAG = 2

TOEIC_SHARE = 0.6  # 其餘為 FLPT 風格
CALIBRATION_ATTEMPTS = 30  # 作答數低於此值時，難度刻意分散以加速定位程度

TOEIC_GENRES = ["email", "memo", "notice", "advertisement", "article", "letter"]
FLPT_GENRES = ["news report", "feature article", "editorial", "academic passage", "public announcement"]


@dataclass(frozen=True)
class Skill:
    tag: str
    section: str
    label_zh: str


@dataclass(frozen=True)
class SkillStat:
    rating: float
    n_attempts: int
    last_seen: datetime | None


@dataclass(frozen=True)
class Slot:
    slot: int
    skill_tag: str
    label_zh: str
    exam_style: str
    target_level: int


@dataclass(frozen=True)
class ReadingPlan:
    exam_style: str
    genre: str
    target_level: int
    slots: list[Slot]


@dataclass
class Plan:
    usage: list[Slot] = field(default_factory=list)
    reading: ReadingPlan | None = None


def rating_of(tag: str, stats: dict[str, SkillStat], base_level: int) -> float:
    s = stats.get(tag)
    return s.rating if s else float(base_level)


def tag_weight(tag: str, stats: dict[str, SkillStat], base_level: int, goal_level: int,
               now: datetime) -> float:
    """弱項、資料少、太久沒練的技能權重較高。"""
    s = stats.get(tag)
    rating = s.rating if s else base_level
    weakness = max(0.0, goal_level - rating) / 100.0
    uncertainty = 1.5 if (s is None or s.n_attempts < 5) else 0.0
    if s is None or s.last_seen is None:
        staleness = 1.0
    else:
        staleness = min((now - s.last_seen).days / 7.0, 1.0)
    return 1.0 + weakness + uncertainty + staleness


def pick_offset(rng: random.Random, calibrating: bool) -> int:
    """難度相對目前能力的偏移量。目標是金色證書，所以偏向略高於目前程度。"""
    if calibrating:
        return rng.choice([-150, -75, 0, 75, 150])
    r = rng.random()
    if r < 0.15:
        return -80
    if r < 0.75:
        return rng.randint(-30, 30)
    return 80


def clamp_level(x: float) -> int:
    return int(min(980, max(400, round(x / 5) * 5)))


def weighted_sample(rng: random.Random, items: list[str], weights: list[float], k: int,
                    max_each: int) -> list[str]:
    counts: dict[str, int] = {}
    out: list[str] = []
    pool = list(zip(items, weights))
    while len(out) < k:
        avail = [(t, w) for t, w in pool if counts.get(t, 0) < max_each]
        if not avail:
            break
        t = rng.choices([t for t, _ in avail], weights=[w for _, w in avail])[0]
        counts[t] = counts.get(t, 0) + 1
        out.append(t)
    return out


def build_plan(skills: list[Skill], stats: dict[str, SkillStat], base_level: int,
               goal_level: int, total_attempts: int, rng: random.Random,
               now: datetime | None = None) -> Plan:
    now = now or datetime.now(timezone.utc)
    calibrating = total_attempts < CALIBRATION_ATTEMPTS
    by_tag = {s.tag: s for s in skills}

    def w(tag: str) -> float:
        return tag_weight(tag, stats, base_level, goal_level, now)

    def style() -> str:
        return "toeic" if rng.random() < TOEIC_SHARE else "flpt"

    plan = Plan()
    slot_no = 0

    # 用法：先保底文法、字彙各幾題，其餘依權重抽
    grammar = [s.tag for s in skills if s.section == "usage" and s.tag.startswith("grammar:")]
    vocab = [s.tag for s in skills if s.section == "usage" and s.tag.startswith("vocab:")]
    chosen: list[str] = []
    if grammar:
        chosen += weighted_sample(rng, grammar, [w(t) for t in grammar], MIN_GRAMMAR, 1)
    if vocab:
        chosen += weighted_sample(rng, vocab, [w(t) for t in vocab], MIN_VOCAB, 1)
    usage_all = grammar + vocab
    if usage_all:
        remaining = USAGE_COUNT - len(chosen)
        counts = {t: chosen.count(t) for t in usage_all}
        extra: list[str] = []
        while len(extra) < remaining:
            avail = [t for t in usage_all if counts[t] < MAX_PER_TAG]
            if not avail:
                break
            t = rng.choices(avail, weights=[w(x) for x in avail])[0]
            counts[t] += 1
            extra.append(t)
        chosen += extra
    rng.shuffle(chosen)
    for tag in chosen:
        level = clamp_level(rating_of(tag, stats, base_level) + pick_offset(rng, calibrating))
        plan.usage.append(Slot(slot_no, tag, by_tag[tag].label_zh, style(), level))
        slot_no += 1

    # 閱讀：一篇文章，題目技能不重複
    reading = [s.tag for s in skills if s.section == "reading"]
    if reading:
        k = min(READING_QUESTIONS, len(reading))
        tags = weighted_sample(rng, reading, [w(t) for t in reading], k, 1)
        exam_style = style()
        genre = rng.choice(TOEIC_GENRES if exam_style == "toeic" else FLPT_GENRES)
        mean = sum(rating_of(t, stats, base_level) for t in tags) / len(tags)
        level = clamp_level(mean + pick_offset(rng, calibrating))
        slots = []
        for tag in tags:
            slots.append(Slot(slot_no, tag, by_tag[tag].label_zh, exam_style, level))
            slot_no += 1
        plan.reading = ReadingPlan(exam_style, genre, level, slots)

    return plan


def expected_correct(difficulty: float, rating: float) -> float:
    """與 submit_attempt() 中的公式相同，供測試與分析使用。"""
    return 0.25 + 0.75 / (1 + math.pow(10, (difficulty - rating) / 150.0))


def today_in(tz_name: str) -> date:
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo(tz_name)).date()
