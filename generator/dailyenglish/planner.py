"""決定今天要出哪些題目：技能、難度、考試風格。純函式，方便測試。"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

# v2 每日題量：約 30 分鐘
#   聽力 9（應答 3、對話 3、獨白 3）＋用法 10＋閱讀約 9（主文章 4–5、短文填空 4）＋錯題複習最多 3
USAGE_COUNT = 10
READING_QUESTIONS = 4          # 單篇文章的題數
REVIEW_MAX = 3
MIN_GRAMMAR = 3
MIN_VOCAB = 3
MAX_PER_TAG = 2

QR_COUNT = 3                   # 聽力應答題數
LISTENING_SET_QUESTIONS = 3    # 對話、獨白各幾題
TEXT_COMPLETION_BLANKS = 4     # 短文填空空格數

TOEIC_SHARE = 0.6  # 其餘為 FLPT 風格
CALIBRATION_ATTEMPTS = 30  # 作答數低於此值時，難度刻意分散以加速定位程度

TOEIC_GENRES = ["email", "memo", "notice", "advertisement", "article", "letter"]
FLPT_GENRES = ["news report", "feature article", "editorial", "academic passage", "public announcement"]

# 文章與聽力情境的主題，每天隨機輪換，避免題材集中在同一領域
TOPICS = [
    "technology and cybersecurity", "health and medicine", "environment and energy",
    "travel and transportation", "education and training", "marketing and sales",
    "finance and economics", "human resources and workplace culture",
    "logistics and supply chain", "food and hospitality", "arts and entertainment",
    "sports and recreation", "urban planning and real estate", "science news",
    "public policy and society", "customer service",
]

# 主文章的格式與權重（短文填空另外固定一組）
MAIN_READING_FORMATS = [("single", 0.4), ("double", 0.25), ("triple", 0.15), ("graphic", 0.2)]
SPECIAL_READING_TAGS = {"reading:text-completion", "reading:sentence-insertion",
                        "reading:multi-passage", "reading:graphic"}


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
    # single | double | triple | graphic | text-completion
    format: str = "single"
    topic: str = ""


@dataclass(frozen=True)
class ListeningPlan:
    format: str          # question-response | conversation | talk
    exam_style: str
    target_level: int
    slots: list[Slot]
    topic: str = ""


@dataclass
class Plan:
    listening: list[ListeningPlan] = field(default_factory=list)
    usage: list[Slot] = field(default_factory=list)
    readings: list[ReadingPlan] = field(default_factory=list)

    @property
    def reading(self) -> ReadingPlan | None:
        """主文章（相容 v1）。"""
        return self.readings[0] if self.readings else None


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
    tags_all = {s.tag for s in skills}

    def level_for(tags: list[str]) -> int:
        mean = sum(rating_of(t, stats, base_level) for t in tags) / len(tags)
        return clamp_level(mean + pick_offset(rng, calibrating))

    def make_slots(tags: list[str], exam_style: str, level: int) -> list[Slot]:
        nonlocal slot_no
        out = []
        for tag in tags:
            out.append(Slot(slot_no, tag, by_tag[tag].label_zh, exam_style, level))
            slot_no += 1
        return out

    # 聽力：應答 3 題（各自一段音檔）＋對話、獨白各一段 3 題。聽力一律多益風格。
    if "listening:question-response" in tags_all:
        for _ in range(QR_COUNT):
            tags = ["listening:question-response"]
            level = level_for(tags)
            plan.listening.append(ListeningPlan("question-response", "toeic", level,
                                                make_slots(tags, "toeic", level),
                                                rng.choice(TOPICS)))
    for fmt in ("conversation", "talk"):
        main = f"listening:{fmt}"
        if main not in tags_all:
            continue
        extra = "listening:inference" if "listening:inference" in tags_all else main
        tags = [main] * (LISTENING_SET_QUESTIONS - 1) + [extra]
        level = level_for(tags)
        plan.listening.append(ListeningPlan(fmt, "toeic", level, make_slots(tags, "toeic", level),
                                            rng.choice(TOPICS)))

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

    # 閱讀主文章：單篇、雙篇、三篇或表格，題目技能不重複
    classic = [s.tag for s in skills if s.section == "reading" and s.tag not in SPECIAL_READING_TAGS]
    if classic:
        formats = [(f, wt) for f, wt in MAIN_READING_FORMATS
                   if f == "single"
                   or (f in ("double", "triple") and "reading:multi-passage" in tags_all)
                   or (f == "graphic" and "reading:graphic" in tags_all)]
        fmt = rng.choices([f for f, _ in formats], weights=[wt for _, wt in formats])[0]
        if fmt == "single":
            special, n_classic = [], READING_QUESTIONS
        elif fmt == "graphic":
            special, n_classic = ["reading:graphic"] * 2, 2
        else:
            special, n_classic = ["reading:multi-passage"] * 2, 3
        picked = weighted_sample(rng, classic, [w(t) for t in classic],
                                 min(n_classic, len(classic)), 1)
        tags = special + picked
        exam_style = style() if fmt == "single" else "toeic"
        genre = rng.choice(TOEIC_GENRES if exam_style == "toeic" else FLPT_GENRES)
        level = level_for(tags)
        plan.readings.append(ReadingPlan(exam_style, genre, level,
                                         make_slots(tags, exam_style, level), fmt,
                                         rng.choice(TOPICS)))

    # 短文填空（多益 Part 6／FLPT 用法短文填空），最後一空考篇章結構
    if "reading:text-completion" in tags_all:
        last = ("reading:sentence-insertion" if "reading:sentence-insertion" in tags_all
                else "reading:text-completion")
        tags = ["reading:text-completion"] * (TEXT_COMPLETION_BLANKS - 1) + [last]
        exam_style = style()
        genre = rng.choice(TOEIC_GENRES if exam_style == "toeic" else FLPT_GENRES)
        level = level_for(tags)
        plan.readings.append(ReadingPlan(exam_style, genre, level,
                                         make_slots(tags, exam_style, level), "text-completion",
                                         rng.choice(TOPICS)))

    return plan


def expected_correct(difficulty: float, rating: float) -> float:
    """與 submit_attempt() 中的公式相同，供測試與分析使用。"""
    return 0.25 + 0.75 / (1 + math.pow(10, (difficulty - rating) / 150.0))


def today_in(tz_name: str) -> date:
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo(tz_name)).date()
