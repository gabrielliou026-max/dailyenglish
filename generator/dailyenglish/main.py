"""每日出題入口。

    python -m dailyenglish.main              # 為每位使用者產生今天的題組
    python -m dailyenglish.main --date 2026-10-12 --force
"""

from __future__ import annotations

import argparse
import logging
import random
import sys
from datetime import date

from . import db
from .items import (LLM, Passage, Stats, generate_listening_set, generate_question_response,
                    generate_reading, generate_usage)
from .planner import REVIEW_MAX, SPECIAL_READING_TAGS, build_plan, today_in
from .tts import TTS, add_audio

log = logging.getLogger("dailyenglish")


def generate_for_user(conn, llm: LLM, model: str, user: dict, on: date | None, force: bool,
                      rng: random.Random, tts: TTS | None = None) -> str:
    uid = user["user_id"]
    on = on or today_in(user["timezone"])

    existing = db.existing_set(conn, uid, on)
    if existing:
        if not force:
            return f"{on}: set already exists, skipped"
        if existing["answered"]:
            return f"{on}: set already has answers, not replacing"
        db.delete_set(conn, existing["id"])
        conn.commit()

    v2 = db.has_v2(conn)
    skills = db.active_skills(conn)
    if not v2:
        # 還沒套用 0002：維持 v1 題型（用法＋單篇閱讀）
        log.warning("migration 0002 not applied; generating v1 set (no listening)")
        skills = [s for s in skills
                  if s.section != "listening" and s.tag not in SPECIAL_READING_TAGS]
    elif tts is None:
        skills = [s for s in skills if s.section != "listening"]
    stats = db.skill_stats(conn, uid)
    plan = build_plan(skills, stats, user["base_level"], user["goal_level"],
                      db.total_attempts(conn, uid), rng)
    avoid = db.recent_focus(conn, uid)
    reviews = db.due_reviews(conn, uid, on, REVIEW_MAX)

    run_id = db.start_run(conn, uid, on, model)
    conn.commit()
    counts = Stats()
    try:
        listening = _listening(llm, plan, avoid, rng, counts, tts)
        avoid = avoid + [it.focus for p in listening for it in p.items]
        usage = generate_usage(llm, plan.usage, avoid, rng, counts)
        avoid = avoid + [i.focus for i in usage]
        readings: list[Passage] = []
        for rp in plan.readings:
            try:
                p = generate_reading(llm, rp, avoid, rng, counts)
            except Exception:
                # 一組閱讀失敗不影響整份題組
                log.exception("reading (%s) failed", rp.format)
                counts.rejected += len(rp.slots)
                continue
            if p:
                readings.append(p)
                avoid = avoid + [it.focus for it in p.items]
        if not usage and not readings and not listening:
            raise RuntimeError("no item survived verification")
        db.save_set(conn, uid, on, usage, readings, reviews, model, listening=listening, v2=v2)
        if v2:
            db.prune_audio(conn, uid)
        db.finish_run(conn, run_id, "ok", *_tokens(llm), counts.accepted, counts.rejected)
        conn.commit()
    except Exception as e:
        conn.rollback()
        db.finish_run(conn, run_id, "error", *_tokens(llm), counts.accepted, counts.rejected,
                      repr(e))
        conn.commit()
        raise
    n_listening = sum(len(p.items) for p in listening)
    n_reading = sum(len(p.items) for p in readings)
    return (f"{on}: {n_listening} listening + {len(usage)} usage + {n_reading} reading + "
            f"{len(reviews)} review (rejected {counts.rejected})")


def _listening(llm: LLM, plan, avoid: list[str], rng: random.Random, counts: Stats,
               tts: TTS | None) -> list[Passage]:
    """聽力出題＋產生音檔。任何一段失敗都只捨棄那一段。"""
    if tts is None or not plan.listening:
        return []
    out: list[Passage] = []
    qr = [p for p in plan.listening if p.format == "question-response"]
    if qr:
        try:
            out += generate_question_response(llm, qr, avoid, rng, counts)
        except Exception:
            log.exception("question-response failed")
            counts.rejected += len(qr)
    for lp in plan.listening:
        if lp.format == "question-response":
            continue
        try:
            p = generate_listening_set(llm, lp, avoid, rng, counts)
        except Exception:
            log.exception("listening %s failed", lp.format)
            counts.rejected += len(lp.slots)
            continue
        if p:
            out.append(p)
    voiced = add_audio(tts, out, rng)
    counts.rejected += sum(len(p.items) for p in out if p not in voiced)
    counts.accepted -= sum(len(p.items) for p in out if p not in voiced)
    return voiced


def _tokens(llm: LLM) -> tuple[int, int]:
    return getattr(llm, "input_tokens", 0), getattr(llm, "output_tokens", 0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=date.fromisoformat, help="題組日期，預設為使用者時區的今天")
    parser.add_argument("--force", action="store_true", help="重新產生（僅限尚未作答的題組）")
    parser.add_argument("--seed", type=int)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    from .llm import ClaudeLLM
    from .tts import KokoroTTS
    llm = ClaudeLLM()
    tts = KokoroTTS.from_env()
    rng = random.Random(args.seed)
    failed = False
    with db.connect() as conn:
        for user in db.users(conn):
            try:
                log.info("%s", generate_for_user(conn, llm, llm.model, user, args.date,
                                                 args.force, rng, tts))
            except Exception:
                log.exception("generation failed for user %s", user["user_id"])
                failed = True
    log.info("tokens: input=%d output=%d", llm.input_tokens, llm.output_tokens)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
