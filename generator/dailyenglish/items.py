"""出題流程：呼叫模型 → 格式檢查 → 獨立驗題 → 打亂選項。"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field, replace
from typing import Protocol

from . import prompts
from .planner import ListeningPlan, ReadingPlan, Slot

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
    kind: str = "reading"                 # reading | listening
    format: str | None = None             # single、double、conversation、question-response…
    script: list[dict] | None = None      # 聽力台詞
    audio: bytes | None = None            # mp3
    duration_ms: int | None = None


@dataclass
class Stats:
    accepted: int = 0
    rejected: int = 0


def check_format(raw: dict, section: str, n_options: int = 4) -> str | None:
    """回傳問題描述；格式正確則回傳 None。"""
    opts = raw.get("options") or []
    notes = raw.get("distractor_notes_zh") or []
    if len(opts) != n_options or any(not str(o).strip() for o in opts):
        return f"need {n_options} non-empty options"
    if len({o.strip().lower() for o in opts}) != n_options:
        return "duplicate options"
    if len(notes) != n_options:
        return f"need {n_options} distractor notes"
    if raw.get("answer_index") not in range(n_options):
        return "answer_index out of range"
    if not str(raw.get("stem", "")).strip() or not str(raw.get("explanation_zh", "")).strip():
        return "empty stem or explanation"
    if section == "usage" and "---" not in raw["stem"]:
        return "usage stem has no blank"
    return None


def shuffle_options(item: Item, rng: random.Random) -> Item:
    order = list(range(len(item.options)))
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
              stats: Stats, n_options: int = 4) -> list[Item]:
    items = []
    seen: set[int] = set()
    for raw in raws:
        slot = slots.get(raw.get("slot"))
        if slot is None or slot.slot in seen:
            stats.rejected += 1
            continue
        problem = check_format(raw, section, n_options)
        if problem:
            stats.rejected += 1
            log.info("format reject slot %s: %s", slot.slot, problem)
            continue
        seen.add(slot.slot)
        items.append(Item(
            slot=slot.slot, skill_tag=slot.skill_tag, exam_style=slot.exam_style,
            section=section, difficulty=slot.target_level, stem=str(raw["stem"]).strip(),
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
                   [shuffle_options(it, rng) for it in kept], kind="reading", format=plan.format)


# ---------------------------------------------------------------------------
# 聽力
# ---------------------------------------------------------------------------
QR_STEM = "Choose the best response."


def clean_script(raw_script) -> list[dict]:
    lines = []
    for ln in raw_script or []:
        if not isinstance(ln, dict):
            continue
        text = " ".join(str(ln.get("text", "")).split())
        if not text:
            continue
        speaker = " ".join(str(ln.get("speaker", "")).split())[:30] or "Speaker"
        lines.append({"speaker": speaker, "gender": "m" if ln.get("gender") == "m" else "f",
                      "text": text})
    return lines


def generate_question_response(llm: LLM, plans: list[ListeningPlan], avoid: list[str],
                               rng: random.Random, stats: Stats) -> list[Passage]:
    """多益 Part 2：每題一句話＋三個口說回應，各自成為一段聽力。"""
    if not plans:
        return []
    raw = llm.json_call(prompts.ITEM_WRITER_SYSTEM, prompts.question_response_prompt(plans, avoid),
                        prompts.QR_SCHEMA)
    by_slot = {p.slots[0].slot: p for p in plans}
    candidates: list[tuple[list[dict], Item]] = []
    seen: set[int] = set()
    for r in raw.get("items", []):
        plan = by_slot.get(r.get("slot"))
        script = clean_script(r.get("script"))[:1]
        if plan is None or plan.slots[0].slot in seen or not script:
            stats.rejected += 1
            continue
        items = _to_items([{**r, "stem": QR_STEM}], {plan.slots[0].slot: plan.slots[0]},
                          "listening", stats, n_options=3)
        if items:
            seen.add(plan.slots[0].slot)
            candidates.append((script, items[0]))
    # 驗題時把那句話放進題幹，讓驗題者「聽得到」題目
    probes = [replace(it, stem=f'{sc[0]["speaker"]} says: "{sc[0]["text"]}" '
                               "Which is the best spoken response?")
              for sc, it in candidates]
    kept = {it.slot for it in verify(llm, probes, None, stats)}
    out = []
    for script, it in candidates:
        if it.slot not in kept:
            continue
        it = shuffle_options(it, rng)
        out.append(Passage("toeic", "question-response", "", prompts.script_text(script), [it],
                           kind="listening", format="question-response", script=script))
    stats.accepted += len(out)
    return out


def generate_listening_set(llm: LLM, plan: ListeningPlan, avoid: list[str], rng: random.Random,
                           stats: Stats) -> Passage | None:
    """多益 Part 3 對話／Part 4 獨白，題目印在畫面上。"""
    raw = llm.json_call(prompts.ITEM_WRITER_SYSTEM, prompts.listening_set_prompt(plan, avoid),
                        prompts.LISTENING_SET_SCHEMA)
    script = clean_script(raw.get("script"))
    if len(script) < 2:
        stats.rejected += len(plan.slots)
        return None
    body = prompts.script_text(script)
    items = _to_items(raw.get("items", []), {s.slot: s for s in plan.slots}, "listening", stats)
    kept = verify(llm, items, body, stats)
    if len(kept) < 2:
        stats.rejected += len(kept)
        return None
    stats.accepted += len(kept)
    kept.sort(key=lambda it: it.slot)
    return Passage(plan.exam_style, plan.format, str(raw.get("title", "")).strip(), body,
                   [shuffle_options(it, rng) for it in kept], kind="listening",
                   format=plan.format, script=script)
