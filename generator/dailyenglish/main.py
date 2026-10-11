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
from .items import LLM, Stats, generate_reading, generate_usage
from .planner import REVIEW_MAX, build_plan, today_in

log = logging.getLogger("dailyenglish")


def generate_for_user(conn, llm: LLM, model: str, user: dict, on: date | None, force: bool,
                      rng: random.Random) -> str:
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

    skills = db.active_skills(conn)
    stats = db.skill_stats(conn, uid)
    plan = build_plan(skills, stats, user["base_level"], user["goal_level"],
                      db.total_attempts(conn, uid), rng)
    avoid = db.recent_focus(conn, uid)
    reviews = db.due_reviews(conn, uid, on, REVIEW_MAX)

    run_id = db.start_run(conn, uid, on, model)
    conn.commit()
    counts = Stats()
    try:
        usage = generate_usage(llm, plan.usage, avoid, rng, counts)
        passage = None
        if plan.reading:
            passage = generate_reading(llm, plan.reading, avoid + [i.focus for i in usage],
                                       rng, counts)
        if not usage and not passage:
            raise RuntimeError("no item survived verification")
        db.save_set(conn, uid, on, usage, passage, reviews, model)
        db.finish_run(conn, run_id, "ok", *_tokens(llm), counts.accepted, counts.rejected)
        conn.commit()
    except Exception as e:
        conn.rollback()
        db.finish_run(conn, run_id, "error", *_tokens(llm), counts.accepted, counts.rejected,
                      repr(e))
        conn.commit()
        raise
    n_reading = len(passage.items) if passage else 0
    return (f"{on}: {len(usage)} usage + {n_reading} reading + {len(reviews)} review "
            f"(rejected {counts.rejected})")


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
    llm = ClaudeLLM()
    rng = random.Random(args.seed)
    failed = False
    with db.connect() as conn:
        for user in db.users(conn):
            try:
                log.info("%s", generate_for_user(conn, llm, llm.model, user, args.date,
                                                 args.force, rng))
            except Exception:
                log.exception("generation failed for user %s", user["user_id"])
                failed = True
    log.info("tokens: input=%d output=%d", llm.input_tokens, llm.output_tokens)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
