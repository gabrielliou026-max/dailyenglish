"""出題流程：呼叫模型 → 格式檢查 → 獨立驗題 → 打亂選項。"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Protocol

from . import prompts
from .planner import ReadingPlan, Slot

log = logging.getLogger(__name__)

MAX_ROUNDS = 2  # 用法題被淘汰時，最多再補出一輪


class LLM(Protocol):
    def json_call(self, system: str, user: str, schema: dict) -> dict: ...


@dataclass
class Item:
    slot: int
    skill_tag: str
    exam_style: str
    section: str
    difficulty: int
    stem: str
    options: list[str]
    answer_index: int
    focus: str
    explanation_zh: str
    distractor_notes_zh: list[str]


@dataclass
class Passage:
    exam_style: str
    genre: str
    title: str
    body: str
    items: list[Item] = field(default_factory=list)


@dataclass
class Stats:
    accepted: int = 0
    rejected: int = 0


def check_format(raw: dict, section: str) -> str | None:
    """回傳問題描述；格式正確則回傳 None。"""
    opts = raw.get("options") or []
    notes = raw.get("distractor_notes_zh") or []
    if len(opts) != 4 or any(not str(o).strip() for o in opts):
        return "need 4 non-empty options"
    if len({o.strip().lower() for o in opts}) != 4:
        return "duplicate options"
    if len(notes) != 4:
        return "need 4 distractor notes"
    if raw.get("answer_index") not in (0, 1, 2, 3):
        return "answer_index out of range"
    if not str(raw.get("stem", "")).strip() or not str(raw.get("explanation_zh", "")).strip():
        return "empty stem or explanation"
    if section == "usage" and "---" not in raw["stem"]:
        return "usage stem has no blank"
    return None


def shuffle_options(item: Item, rng: random.Random) -> Item:
    order = list(range(4))
    rng.shuffle(order)
    item.options = [item.options[i] for i in order]
    item.distractor_notes_zh = [item.distractor_notes_zh[i] for i in order]
    item.answer_index = order.index(item.answer_index)
    return item


def verify(llm: LLM, items: list[Item], passage: str | None, stats: Stats) -> list[Item]:
    """讓模型在不知道答案的情況下作答；答案不同或判定有歧義的題目丟掉。"""
    if not items:
        return []
    payload = [{"id": str(it.slot), "stem": it.stem, "options": it.options} for it in items]
    result = llm.json_call(prompts.VERIFIER_SYSTEM, prompts.verify_prompt(payload, passage),
                           prompts.VERIFY_SCHEMA)
    verdicts = {r["id"]: r for r in result.get("results", [])}
    kept = []
    for it in items:
        v = verdicts.get(str(it.slot))
        if v and v["answer_index"] == it.answer_index and not v["ambiguous"]:
            kept.append(it)
        else:
            stats.rejected += 1
            log.info("rejected slot %s (%s): verifier=%s", it.slot, it.focus, v)
    return kept


def _to_items(raws: list[dict], slots: dict[int, Slot], section: str,
              stats: Stats) -> list[Item]:
    items = []
    seen: set[int] = set()
    for raw in raws:
        slot = slots.get(raw.get("slot"))
        if slot is None or slot.slot in seen:
            stats.rejected += 1
            continue
        problem = check_format(raw, section)
        if problem:
            stats.rejected += 1
            log.info("format reject slot %s: %s", slot.slot, problem)
            continue
        seen.add(slot.slot)
        items.append(Item(
            slot=slot.slot, skill_tag=slot.skill_tag, exam_style=slot.exam_style,
            section=section, difficulty=slot.target_level, stem=raw["stem"].strip(),
            options=[o.strip() for o in raw["options"]], answer_index=raw["answer_index"],
            focus=raw["focus"].strip(), explanation_zh=raw["explanation_zh"].strip(),
            distractor_notes_zh=[n.strip() for n in raw["distractor_notes_zh"]],
        ))
    return items


def generate_usage(llm: LLM, slots: list[Slot], avoid: list[str], rng: random.Random,
                   stats: Stats) -> list[Item]:
    accepted: list[Item] = []
    pending = list(slots)
    for _ in range(MAX_ROUNDS):
        if not pending:
            break
        raw = llm.json_call(prompts.ITEM_WRITER_SYSTEM, prompts.usage_prompt(pending, avoid),
                            prompts.USAGE_SCHEMA)
        items = _to_items(raw.get("items", []), {s.slot: s for s in pending}, "usage", stats)
        kept = verify(llm, items, None, stats)
        accepted += kept
        done = {it.slot for it in kept}
        pending = [s for s in pending if s.slot not in done]
        avoid = avoid + [it.focus for it in kept]
    stats.accepted += len(accepted)
    accepted.sort(key=lambda it: it.slot)
    return [shuffle_options(it, rng) for it in accepted]


def generate_reading(llm: LLM, plan: ReadingPlan, avoid: list[str], rng: random.Random,
                     stats: Stats) -> Passage | None:
    raw = llm.json_call(prompts.ITEM_WRITER_SYSTEM, prompts.reading_prompt(plan, avoid),
                        prompts.READING_SCHEMA)
    body = str(raw.get("passage", "")).strip()
    if not body:
        stats.rejected += len(plan.slots)
        return None
    items = _to_items(raw.get("items", []), {s.slot: s for s in plan.slots}, "reading", stats)
    kept = verify(llm, items, body, stats)
    if len(kept) < 2:  # 一篇只剩 1 題不划算，整篇放棄
        stats.rejected += len(kept)
        return None
    stats.accepted += len(kept)
    kept.sort(key=lambda it: it.slot)
    return Passage(plan.exam_style, plan.genre, str(raw.get("title", "")).strip(), body,
                   [shuffle_options(it, rng) for it in kept])
