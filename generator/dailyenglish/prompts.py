"""出題與驗題的 prompt 與 JSON schema。"""

from __future__ import annotations

import json

from .planner import ListeningPlan, ReadingPlan, Slot

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

_LINE_SCHEMA = {
    "type": "object",
    "properties": {
        "speaker": {"type": "string"},
        "gender": {"type": "string", "enum": ["f", "m"]},
        "text": {"type": "string"},
    },
    "required": ["speaker", "gender", "text"],
    "additionalProperties": False,
}

_QR_PROPS = {
    "slot": {"type": "integer"},
    "script": {"type": "array", "items": _LINE_SCHEMA},
    "options": _str_array(),
    "answer_index": {"type": "integer"},
    "focus": {"type": "string"},
    "explanation_zh": {"type": "string"},
    "distractor_notes_zh": _str_array(),
}
QR_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "properties": _QR_PROPS, "required": list(_QR_PROPS),
        "additionalProperties": False}}},
    "required": ["items"],
    "additionalProperties": False,
}

LISTENING_SET_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "script": {"type": "array", "items": _LINE_SCHEMA},
        "items": {"type": "array", "items": _ITEM_SCHEMA},
    },
    "required": ["title", "script", "items"],
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


_CLASSIC_SKILLS = (
    "main-idea, detail, inference, vocab-in-context (quote the word and its paragraph), "
    "purpose-tone, or not-true (\"Which of the following is NOT ...\")"
)
_TABLE_RULE = ("Write any table as plain text: one row per line, cells separated by \" | \", "
               "the first row is the header.")


def _reading_format_rules(plan: ReadingPlan) -> tuple[str, str]:
    """回傳（文章格式說明, 題目說明）。"""
    n = len(plan.slots)
    if plan.format in ("double", "triple"):
        k = 2 if plan.format == "double" else 3
        words = "280-360" if k == 2 else "360-450"
        return (
            f"TOEIC Part 7 {'double' if k == 2 else 'triple'} passage: {k} related documents "
            f"(for example e-mail + schedule, advertisement + review, web page + form + "
            f"confirmation e-mail), {words} words in total. Start each document with its own "
            f"line \"[Document 1]\", \"[Document 2]\"{', \"[Document 3]\"' if k == 3 else ''}. "
            f"{_TABLE_RULE}",
            "reading:multi-passage questions must require combining facts from at least two "
            f"documents. Other questions test their skill: {_CLASSIC_SKILLS}.",
        )
    if plan.format == "graphic":
        return (
            "A short business text (60-120 words) plus one table of data (price list, schedule, "
            f"survey result, sales figures, invoice, etc.). {_TABLE_RULE}",
            "reading:graphic questions must require reading, comparing or doing simple "
            f"arithmetic with the table. Other questions test their skill: {_CLASSIC_SKILLS}.",
        )
    if plan.format == "text-completion":
        words = "140-190" if plan.exam_style == "toeic" else "180-230"
        return (
            f"{'TOEIC Part 6' if plan.exam_style == 'toeic' else 'FLPT usage cloze'}: one "
            f"{words}-word text with exactly {n} blanks written [1], [2], ... in order of the "
            "specs. The blanks replace words that are tested; do not write the answers anywhere.",
            "Each stem is exactly \"Blank [k]\" for its blank number. reading:text-completion "
            "blanks test a word, phrase, verb form or connector that depends on the surrounding "
            "sentences, not on the blank's own sentence alone. reading:sentence-insertion "
            "options are four complete sentences; exactly one fits the blank logically.",
        )
    words = "180-260" if plan.exam_style == "toeic" else "250-350"
    return (f"One passage, {words} words.",
            f"One question per spec, testing that reading skill: {_CLASSIC_SKILLS}.")


def reading_prompt(plan: ReadingPlan, avoid: list[str]) -> str:
    text_rule, question_rule = _reading_format_rules(plan)
    specs = [{"slot": s.slot, "skill": s.skill_tag} for s in plan.slots]
    stem_rule = ("" if plan.format == "text-completion" else
                 "- Each stem is a complete question with no blank. Answers must be supported "
                 "by the passage alone, not outside knowledge.\n")
    return (
        f"Write one reading set and {len(plan.slots)} questions about it.\n"
        f"- exam_style: {plan.exam_style}; genre: {plan.genre}; topic area: "
        f"{plan.topic or 'any'}; target_level: {plan.target_level}.\n"
        f"- Format: {text_rule}\n"
        "- Put the full text in passage and a short title in title. Use plain text with blank "
        "lines between paragraphs; no markdown.\n"
        f"- {question_rule}\n"
        f"{stem_rule}"
        "- Echo each spec's slot number.\n\n"
        f"Specs:\n{json.dumps(specs, ensure_ascii=False)}\n\n"
        f"Avoid: {json.dumps(avoid, ensure_ascii=False)}"
    )


_SPOKEN_RULE = (
    "The script is read aloud by a text-to-speech engine: write only the spoken words, with no "
    "stage directions, sound effects, brackets, emoji or abbreviations that are awkward to read "
    "aloud (write \"nine thirty\" or \"9:30\", not \"9:30a\"). Use contractions and natural "
    "spoken English. gender is \"f\" or \"m\"."
)


def question_response_prompt(plans: list[ListeningPlan], avoid: list[str]) -> str:
    specs = [{"slot": p.slots[0].slot, "target_level": p.target_level, "topic_area": p.topic}
             for p in plans]
    return (
        "Write one TOEIC Part 2 question-response item per spec.\n"
        "- script: exactly one line, a question or statement by one speaker (6-16 words).\n"
        "- options: exactly THREE spoken responses by a different speaker. They are heard, not "
        "read, so keep each under 14 words. distractor_notes_zh has three notes in the same "
        "order. answer_index is 0, 1 or 2.\n"
        "- Use real Part 2 traps: the correct answer is often indirect (a question back, \"I "
        "haven't heard yet\"); distractors repeat a word from the prompt, use a similar-sounding "
        "word, or answer a different wh-question.\n"
        f"- {_SPOKEN_RULE}\n"
        "- Rule 2 about four options does not apply here; all other rules do.\n"
        "- Echo each spec's slot number.\n\n"
        f"Specs:\n{json.dumps(specs, ensure_ascii=False)}\n\n"
        f"Avoid: {json.dumps(avoid, ensure_ascii=False)}"
    )


def listening_set_prompt(plan: ListeningPlan, avoid: list[str]) -> str:
    specs = [{"slot": s.slot, "skill": s.skill_tag} for s in plan.slots]
    if plan.format == "conversation":
        shape = ("TOEIC Part 3 conversation: 6-10 turns between two or three speakers, at least "
                 "one woman and one man. speaker is the person's first name.")
    else:
        shape = ("TOEIC Part 4 talk by one speaker, 5-8 sentences: an announcement, voicemail, "
                 "broadcast, tour introduction, meeting opening or advertisement. Put each "
                 "sentence or two in its own script line, all with the same speaker.")
    return (
        f"Write one listening set and {len(plan.slots)} printed questions about it.\n"
        f"- {shape}\n"
        f"- topic area: {plan.topic or 'any workplace or everyday situation'}; "
        f"target_level: {plan.target_level}.\n"
        f"- {_SPOKEN_RULE}\n"
        "- title: a short description of the situation (shown after answering).\n"
        "- Questions are printed with four options. listening:conversation / listening:talk "
        "questions ask about the topic, a detail, or what a speaker will do next; "
        "listening:inference questions ask what a speaker implies or means by a quoted phrase. "
        "Answers must follow from the script alone.\n"
        "- Echo each spec's slot number.\n\n"
        f"Specs:\n{json.dumps(specs, ensure_ascii=False)}\n\n"
        f"Avoid: {json.dumps(avoid, ensure_ascii=False)}"
    )


def script_text(script: list[dict]) -> str:
    """聽力稿轉成純文字（驗題與顯示用）。"""
    return "\n".join(f"{ln['speaker']}: {ln['text']}" for ln in script)


def verify_prompt(items: list[dict], passage: str | None) -> str:
    payload = [{"id": it["id"], "stem": it["stem"], "options": it["options"]} for it in items]
    head = f"Passage:\n{passage}\n\n" if passage else ""
    return (
        f"{head}Answer each item. answer_index is 0-based.\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=1)}"
    )
