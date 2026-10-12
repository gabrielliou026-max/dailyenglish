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


def has_v2(conn) -> bool:
    """0002 migration（聽力、音檔、新閱讀題型）是否已套用。"""
    row = conn.execute(
        """select to_regclass('public.audio_clips') is not null
                  and exists (select 1 from information_schema.columns
                               where table_schema = 'public' and table_name = 'passages'
                                 and column_name = 'audio_id') as ok""").fetchone()
    return bool(row["ok"])


def prune_audio(conn, user_id: UUID, keep_days: int = 60) -> int:
    """刪掉舊音檔（仍在錯題複習中的保留），控制資料庫大小。"""
    cur = conn.execute(
        """delete from audio_clips c
            where c.user_id = %s and c.created_at < now() - make_interval(days => %s)
              and not exists (
                select 1 from passages p
                  join questions q on q.passage_id = p.id
                  join review_queue r on r.question_id = q.id
                 where p.audio_id = c.id)""",
        (user_id, keep_days))
    return cur.rowcount


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


def _insert_passage(conn, user_id: UUID, p: Passage, v2: bool) -> UUID:
    if not v2:
        return conn.execute(
            """insert into passages (user_id, exam_style, genre, title, body)
               values (%s, %s, %s, %s, %s) returning id""",
            (user_id, p.exam_style, p.genre, p.title, p.body)).fetchone()["id"]
    audio_id = None
    if p.audio:
        audio_id = conn.execute(
            """insert into audio_clips (user_id, mime, duration_ms, data)
               values (%s, 'audio/mpeg', %s, %s) returning id""",
            (user_id, p.duration_ms, p.audio)).fetchone()["id"]
    return conn.execute(
        """insert into passages (user_id, exam_style, genre, title, body, kind, format, script,
                                 audio_id)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s) returning id""",
        (user_id, p.exam_style, p.genre, p.title, p.body, p.kind, p.format,
         Jsonb(p.script) if p.script is not None else None, audio_id)).fetchone()["id"]


def save_set(conn, user_id: UUID, on: date, usage: list[Item], passages: list[Passage],
             reviews: list[UUID], model: str, listening: list[Passage] | None = None,
             v2: bool = False) -> UUID:
    """順序：聽力 → 用法 → 閱讀 → 錯題複習（與正式考試相同，先聽後讀）。"""
    set_id = conn.execute(
        "insert into daily_sets (user_id, set_date) values (%s, %s) returning id",
        (user_id, on)).fetchone()["id"]
    entries: list[tuple[UUID, bool]] = []

    def add_passage(p: Passage) -> None:
        pid = _insert_passage(conn, user_id, p, v2)
        for it in p.items:
            entries.append((_insert_question(conn, user_id, on, it, pid, model), False))

    for p in listening or []:
        add_passage(p)
    for it in usage:
        entries.append((_insert_question(conn, user_id, on, it, None, model), False))
    for p in passages:
        add_passage(p)
    entries += [(qid, True) for qid in reviews]
    for pos, (qid, is_review) in enumerate(entries):
        conn.execute(
            """insert into daily_set_items (set_id, position, question_id, is_review)
               values (%s, %s, %s, %s)""",
            (set_id, pos, qid, is_review))
    return set_id
