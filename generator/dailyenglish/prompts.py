"""出題與驗題的 prompt 與 JSON schema。"""

from __future__ import annotations

import json

from .planner import ReadingPlan, Slot

ITEM_WRITER_SYSTEM = """\
You write multiple-choice items for an adult Taiwanese learner preparing for two exams:
- TOEIC Listening & Reading (goal: 860+ gold certificate). Workplace and everyday business contexts.
- FLPT English (Taiwan LTTC Foreign Language Proficiency Test, goal: 240/300). General, news, \
government and academic contexts. The learner works in military communications.

Difficulty is expressed on the TOEIC 10-990 scale: the score of a test taker who would answer \
the item correctly about 60% of the time. Anchors:
- ~550: high-frequency words, basic tense and agreement, obvious distractors.
- ~700: common business vocabulary, standard clause structures.
- ~800: less frequent words (e.g. reimburse, tentative), word-form traps, conjunction logic.
- ~900: formal or low-frequency vocabulary, subtle collocations, participial constructions, \
inversion, distractors that are grammatical but wrong in context.
- ~970: near-synonym distinctions that require precise collocation or register knowledge.

Rules for every item:
1. Exactly one option is correct. Every distractor must be clearly wrong to an expert, \
while staying plausible to a learner at the target level.
2. Four options of similar length and form. Never use "all of the above" or "none of the above".
3. Natural, modern, error-free English (American spelling unless the passage is British). \
Write original content; do not reproduce published test items.
4. explanation_zh: in Traditional Chinese as used in Taiwan, 2-4 sentences, explaining why the \
answer is correct and the rule or meaning tested. Refer to options by their English wording, \
never by letter or position, because options will be shuffled.
5. distractor_notes_zh: one short Traditional Chinese note per option, in the same order as \
options. For the correct option write why it fits; for each distractor write why it is wrong.
6. focus: the specific point tested, in English, short (e.g. "reimburse", \
"mixed conditional", "in compliance with").
7. Do not reuse any focus listed under "Avoid".
"""

VERIFIER_SYSTEM = """\
You are a strict reviewer of English multiple-choice test items. For each item, decide the single \
best answer yourself. Mark ambiguous=true if more than one option could reasonably be defended, if \
no option is correct, or if the item contains an English error. Keep note short."""


def _str_array() -> dict:
    return {"type": "array", "items": {"type": "string"}}


_ITEM_PROPS = {
    "slot": {"type": "integer"},
    "stem": {"type": "string"},
    "options": _str_array(),
    "answer_index": {"type": "integer"},
    "focus": {"type": "string"},
    "explanation_zh": {"type": "string"},
    "distractor_notes_zh": _str_array(),
}
_ITEM_SCHEMA = {
    "type": "object",
    "properties": _ITEM_PROPS,
    "required": list(_ITEM_PROPS),
    "additionalProperties": False,
}

USAGE_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": _ITEM_SCHEMA}},
    "required": ["items"],
    "additionalProperties": False,
}

READING_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "passage": {"type": "string"},
        "items": {"type": "array", "items": _ITEM_SCHEMA},
    },
    "required": ["title", "passage", "items"],
    "additionalProperties": False,
}

VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "answer_index": {"type": "integer"},
                    "ambiguous": {"type": "boolean"},
                    "note": {"type": "string"},
                },
                "required": ["id", "answer_index", "ambiguous", "note"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}


def usage_prompt(slots: list[Slot], avoid: list[str]) -> str:
    specs = [
        {"slot": s.slot, "skill": s.skill_tag, "exam_style": s.exam_style,
         "target_level": s.target_level}
        for s in slots
    ]
    return (
        "Write one sentence-completion item per spec below.\n"
        "- The stem is a single sentence (or two short sentences) with exactly one blank "
        "written as \"-------\".\n"
        "- grammar:* skills test that grammar point; vocab:* skills test word choice in that "
        "domain (vocab:collocation and vocab:phrasal-idiom may use any domain).\n"
        "- exam_style toeic: workplace / business setting. exam_style flpt: news, government, "
        "society, science or academic setting.\n"
        "- Echo each spec's slot number.\n\n"
        f"Specs:\n{json.dumps(specs, ensure_ascii=False, indent=1)}\n\n"
        f"Avoid: {json.dumps(avoid, ensure_ascii=False)}"
    )


def reading_prompt(plan: ReadingPlan, avoid: list[str]) -> str:
    words = "180-260" if plan.exam_style == "toeic" else "250-350"
    specs = [{"slot": s.slot, "skill": s.skill_tag} for s in plan.slots]
    return (
        f"Write one reading passage and {len(plan.slots)} questions about it.\n"
        f"- exam_style: {plan.exam_style}; genre: {plan.genre}; length: {words} words; "
        f"target_level: {plan.target_level}.\n"
        "- Put the full passage text in passage and a short title in title. Use plain text "
        "with blank lines between paragraphs; no markdown.\n"
        "- One question per spec, testing that reading skill: main-idea, detail, inference, "
        "vocab-in-context (quote the word and its paragraph), purpose-tone, or not-true "
        "(\"Which of the following is NOT ...\").\n"
        "- Each stem is a complete question with no blank. Answers must be supported by the "
        "passage alone, not outside knowledge.\n"
        "- Echo each spec's slot number.\n\n"
        f"Specs:\n{json.dumps(specs, ensure_ascii=False)}\n\n"
        f"Avoid: {json.dumps(avoid, ensure_ascii=False)}"
    )


def verify_prompt(items: list[dict], passage: str | None) -> str:
    payload = [{"id": it["id"], "stem": it["stem"], "options": it["options"]} for it in items]
    head = f"Passage:\n{passage}\n\n" if passage else ""
    return (
        f"{head}Answer each item. answer_index is 0-based.\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=1)}"
    )
