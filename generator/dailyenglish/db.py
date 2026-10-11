"""資料庫存取（直連 Supabase Postgres，以 postgres 身分執行，不受 RLS 限制）。"""

from __future__ import annotations

import os
from datetime import date
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .items import Item, Passage
from .planner import Skill, SkillStat


def connect() -> psycopg.Connection:
    # prepare_threshold=None：Supabase transaction pooler（port 6543）不支援 prepared statements
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row,
                           prepare_threshold=None)


def users(conn) -> list[dict]:
    return conn.execute(
        "select user_id, base_level, goal_level, timezone from profiles order by created_at"
    ).fetchall()


def active_skills(conn) -> list[Skill]:
    rows = conn.execute(
        "select tag, section, label_zh from skills where active order by sort").fetchall()
    return [Skill(r["tag"], r["section"], r["label_zh"]) for r in rows]


def skill_stats(conn, user_id: UUID) -> dict[str, SkillStat]:
    rows = conn.execute(
        "select skill_tag, rating, n_attempts, last_seen from skill_stats where user_id = %s",
        (user_id,)).fetchall()
    return {r["skill_tag"]: SkillStat(r["rating"], r["n_attempts"], r["last_seen"]) for r in rows}


def total_attempts(conn, user_id: UUID) -> int:
    return conn.execute("select count(*) as n from attempts where user_id = %s",
                        (user_id,)).fetchone()["n"]


def recent_focus(conn, user_id: UUID, limit: int = 80) -> list[str]:
    rows = conn.execute(
        "select focus from questions where user_id = %s order by created_at desc limit %s",
        (user_id, limit)).fetchall()
    return [r["focus"] for r in rows]


def due_reviews(conn, user_id: UUID, on: date, limit: int) -> list[UUID]:
    rows = conn.execute(
        """select r.question_id from review_queue r
             join questions q on q.id = r.question_id
            where r.user_id = %s and r.due_on <= %s and q.status = 'active'
            order by r.due_on, r.lapses desc limit %s""",
        (user_id, on, limit)).fetchall()
    return [r["question_id"] for r in rows]


def existing_set(conn, user_id: UUID, on: date) -> dict | None:
    return conn.execute(
        """select s.id, (select count(*) from attempts a where a.set_id = s.id) as answered
             from daily_sets s where s.user_id = %s and s.set_date = %s""",
        (user_id, on)).fetchone()


def delete_set(conn, set_id: UUID) -> None:
    conn.execute("delete from daily_sets where id = %s", (set_id,))


def start_run(conn, user_id: UUID, on: date, model: str) -> int:
    return conn.execute(
        "insert into generation_runs (user_id, set_date, model) values (%s, %s, %s) returning id",
        (user_id, on, model)).fetchone()["id"]


def finish_run(conn, run_id: int, status: str, input_tokens: int, output_tokens: int,
               accepted: int, rejected: int, error: str | None = None) -> None:
    conn.execute(
        """update generation_runs set finished_at = now(), status = %s, input_tokens = %s,
                  output_tokens = %s, n_accepted = %s, n_rejected = %s, error = %s
            where id = %s""",
        (status, input_tokens, output_tokens, accepted, rejected, error, run_id))


def _insert_question(conn, user_id: UUID, on: date, it: Item, passage_id: UUID | None,
                     model: str) -> UUID:
    return conn.execute(
        """insert into questions (user_id, created_on, exam_style, section, skill_tag, focus,
                                  difficulty, passage_id, stem, options, answer_index,
                                  explanation_zh, distractor_notes_zh, model)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id""",
        (user_id, on, it.exam_style, it.section, it.skill_tag, it.focus, it.difficulty,
         passage_id, it.stem, Jsonb(it.options), it.answer_index, it.explanation_zh,
         Jsonb(it.distractor_notes_zh), model)).fetchone()["id"]


def save_set(conn, user_id: UUID, on: date, usage: list[Item], passage: Passage | None,
             reviews: list[UUID], model: str) -> UUID:
    """順序：用法 → 閱讀 → 錯題複習。"""
    set_id = conn.execute(
        "insert into daily_sets (user_id, set_date) values (%s, %s) returning id",
        (user_id, on)).fetchone()["id"]
    entries: list[tuple[UUID, bool]] = []
    for it in usage:
        entries.append((_insert_question(conn, user_id, on, it, None, model), False))
    if passage:
        pid = conn.execute(
            """insert into passages (user_id, exam_style, genre, title, body)
               values (%s, %s, %s, %s, %s) returning id""",
            (user_id, passage.exam_style, passage.genre, passage.title, passage.body)
        ).fetchone()["id"]
        for it in passage.items:
            entries.append((_insert_question(conn, user_id, on, it, pid, model), False))
    entries += [(qid, True) for qid in reviews]
    for pos, (qid, is_review) in enumerate(entries):
        conn.execute(
            """insert into daily_set_items (set_id, position, question_id, is_review)
               values (%s, %s, %s, %s)""",
            (set_id, pos, qid, is_review))
    return set_id
