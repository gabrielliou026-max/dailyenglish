"""以假 LLM 跑完整出題流程，並透過 submit_attempt() 模擬作答。

需要已套用 supabase/tests/local_auth_stub.sql 與 migrations 的 PostgreSQL：
    TEST_DATABASE_URL=postgresql://postgres@localhost:54329/de_test pytest
"""

import os
import random
import uuid
from datetime import date

import psycopg
import pytest
from psycopg.rows import dict_row

from dailyenglish import db as dbmod
from dailyenglish import prompts
from dailyenglish.main import generate_for_user

DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")


class FakeLLM:
    """出題時正解永遠放第 0 個；驗題時可指定要「答錯」的 slot。"""

    def __init__(self, disagree_slots=()):
        self.disagree = {str(s) for s in disagree_slots}
        self.calls = []

    def json_call(self, system, user, schema):
        self.calls.append(schema)
        if schema is prompts.VERIFY_SCHEMA:
            import json
            payload = json.loads(user[user.index("["):])
            hit = {p["id"] for p in payload} & self.disagree
            self.disagree -= hit  # 只在第一次不一致，補出那輪就通過
            return {"results": [
                {"id": p["id"], "answer_index": 1 if p["id"] in hit else 0,
                 "ambiguous": False, "note": ""} for p in payload]}
        import json
        specs = json.loads(user[user.index("Specs:") + 6:user.index("Avoid:")])
        if schema is prompts.QR_SCHEMA:
            return {"items": [{
                "slot": s["slot"],
                "script": [{"speaker": "A", "gender": "f", "text": f"Where is room {s['slot']}?"}],
                "options": [f"Down the hall {s['slot']}.", f"A room {s['slot']}.",
                            f"At noon {s['slot']}."],
                "answer_index": 0,
                "focus": f"qr-{s['slot']}-{uuid.uuid4().hex[:4]}",
                "explanation_zh": "說明",
                "distractor_notes_zh": ["對", "錯", "錯"],
            } for s in specs]}
        items = [{
            "slot": s["slot"],
            "stem": f"The manager ------- item {s['slot']}." if schema is prompts.USAGE_SCHEMA
                    else f"What is true about item {s['slot']}?",
            "options": [f"right {s['slot']}", f"wrong a{s['slot']}", f"wrong b{s['slot']}",
                        f"wrong c{s['slot']}"],
            "answer_index": 0,
            "focus": f"focus-{s['slot']}-{uuid.uuid4().hex[:4]}",
            "explanation_zh": "說明",
            "distractor_notes_zh": ["對", "錯", "錯", "錯"],
        } for s in specs]
        if schema is prompts.READING_SCHEMA:
            return {"title": "Notice", "passage": "Body text.", "items": items}
        if schema is prompts.LISTENING_SET_SCHEMA:
            return {"title": "Office move", "items": items, "script": [
                {"speaker": "Mark", "gender": "m", "text": "Are the boxes ready?"},
                {"speaker": "Lisa", "gender": "f", "text": "Almost, give me ten minutes."}]}
        return {"items": items}


class FakeTTS:
    def __init__(self):
        self.calls = []

    def render(self, segments):
        self.calls.append(segments)
        return b"ID3-fake-mp3", 1500


@pytest.fixture
def conn():
    with psycopg.connect(DB_URL, row_factory=dict_row) as c:
        uid = uuid.uuid4()
        c.execute("insert into auth.users (id, email) values (%s, %s)", (uid, f"{uid}@t"))
        c.commit()
        c.uid = uid
        yield c
        c.rollback()
        c.execute("delete from auth.users where id = %s", (uid,))
        c.commit()


def user_row(conn):
    return conn.execute("select * from profiles where user_id = %s", (conn.uid,)).fetchone()


def as_user(conn, uid):
    conn.execute("select set_config('request.jwt.claim.sub', %s, false)", (str(uid),))


def set_items(conn, on):
    return conn.execute(
        """select i.*, q.answer_index, q.skill_tag, q.section, q.passage_id
             from daily_set_items i join daily_sets s on s.id = i.set_id
             join questions q on q.id = i.question_id
            where s.user_id = %s and s.set_date = %s order by i.position""",
        (conn.uid, on)).fetchall()


def submit(conn, item, chosen):
    return conn.execute("select submit_attempt(%s, %s, %s::smallint, %s) as r",
                        (item["set_id"], item["question_id"], chosen, 9000)).fetchone()["r"]


def test_profile_created_by_trigger(conn):
    assert user_row(conn)["base_level"] == 805


def test_generate_and_answer(conn):
    day1 = date(2026, 10, 12)
    llm = FakeLLM(disagree_slots=[3])  # slot 3 驗題不一致 → 補出一輪
    msg = generate_for_user(conn, llm, "fake", user_row(conn), day1, False, random.Random(1))
    assert "0 listening + 10 usage + " in msg and " + 0 review" in msg  # 沒有 TTS → 不出聽力

    items = set_items(conn, day1)
    sections = [i["section"] for i in items]
    assert sections[:10] == ["usage"] * 10 and set(sections[10:]) == {"reading"}
    assert 8 <= sections.count("reading") <= 9          # 主文章 4–5 題＋短文填空 4 題
    assert len({i["passage_id"] for i in items if i["section"] == "reading"}) == 2
    # 選項有被打亂，正解不會總在第 0 個
    assert len({i["answer_index"] for i in items}) > 1

    run = conn.execute("select * from generation_runs where user_id = %s",
                       (conn.uid,)).fetchone()
    assert run["status"] == "ok" and run["n_rejected"] >= 1

    # 第二次執行不覆蓋
    assert "skipped" in generate_for_user(conn, llm, "fake", user_row(conn), day1, False,
                                          random.Random(1))

    as_user(conn, conn.uid)
    wrong_item, right_item = items[0], items[1]
    r = submit(conn, wrong_item, (wrong_item["answer_index"] + 1) % 4)
    assert r["is_correct"] is False and r["rating_after"] < r["rating_before"] == 805
    r = submit(conn, right_item, right_item["answer_index"])
    assert r["is_correct"] is True
    # 重複送出回傳原結果
    assert submit(conn, wrong_item, wrong_item["answer_index"])["duplicate"] is True

    rq = conn.execute("select * from review_queue where user_id = %s", (conn.uid,)).fetchall()
    assert [q["question_id"] for q in rq] == [wrong_item["question_id"]]
    assert rq[0]["interval_days"] == 1

    for it in items[2:]:
        submit(conn, it, it["answer_index"])
    assert conn.execute("select completed_at from daily_sets where id = %s",
                        (items[0]["set_id"],)).fetchone()["completed_at"] is not None

    # 隔天：錯題出現在複習區
    conn.execute("update review_queue set due_on = %s", (date(2026, 10, 13),))
    conn.commit()
    day2 = date(2026, 10, 13)
    msg = generate_for_user(conn, FakeLLM(), "fake", user_row(conn), day2, False,
                            random.Random(2))
    assert "1 review" in msg
    items2 = set_items(conn, day2)
    review = [i for i in items2 if i["is_review"]]
    assert [i["question_id"] for i in review] == [wrong_item["question_id"]]

    before = conn.execute("select rating from skill_stats where user_id = %s and skill_tag = %s",
                          (conn.uid, review[0]["skill_tag"])).fetchone()["rating"]
    r = submit(conn, review[0], review[0]["answer_index"])
    assert r["is_correct"] is True and r["rating_after"] is None  # 複習題不影響能力值
    after = conn.execute("select rating from skill_stats where user_id = %s and skill_tag = %s",
                         (conn.uid, review[0]["skill_tag"])).fetchone()["rating"]
    assert before == after
    assert conn.execute("select interval_days from review_queue where question_id = %s",
                        (review[0]["question_id"],)).fetchone()["interval_days"] == 3


def test_rls_and_flag(conn):
    day = date(2026, 10, 12)
    generate_for_user(conn, FakeLLM(), "fake", user_row(conn), day, False, random.Random(3))
    items = set_items(conn, day)

    other = uuid.uuid4()
    conn.execute("insert into auth.users (id, email) values (%s, 'other@t')", (other,))
    conn.commit()
    try:
        conn.execute("set role authenticated")
        as_user(conn, other)
        assert conn.execute("select count(*) as n from questions").fetchone()["n"] == 0
        with pytest.raises(psycopg.errors.RaiseException):
            submit(conn, items[0], 0)
        conn.rollback()

        conn.execute("set role authenticated")
        as_user(conn, conn.uid)
        assert conn.execute("select count(*) as n from questions").fetchone()["n"] == len(items)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("insert into attempts (user_id, set_id, question_id, chosen_index, "
                         "is_correct) values (%s, %s, %s, 0, true)",
                         (conn.uid, items[0]["set_id"], items[0]["question_id"]))
        conn.rollback()

        conn.execute("set role authenticated")
        as_user(conn, conn.uid)
        conn.execute("select flag_question(%s, 'bad')", (items[0]["question_id"],))
        r = submit(conn, items[0], (items[0]["answer_index"] + 1) % 4)
        assert r["rating_after"] is None
        assert conn.execute("select count(*) as n from review_queue").fetchone()["n"] == 0
        conn.commit()
    finally:
        conn.execute("reset role")
        conn.execute("delete from auth.users where id = %s", (other,))
        conn.commit()


def test_listening_set_with_audio(conn):
    day = date(2026, 10, 14)
    tts = FakeTTS()
    msg = generate_for_user(conn, FakeLLM(), "fake", user_row(conn), day, False,
                            random.Random(5), tts)
    assert msg.startswith(f"{day}: 9 listening + 10 usage + ")
    items = set_items(conn, day)
    assert [i["section"] for i in items][:9] == ["listening"] * 9   # 先聽後讀
    assert len(tts.calls) == 5                                      # 應答 3 段＋對話＋獨白

    rows = conn.execute(
        """select p.format, p.kind, p.audio_id, p.script, jsonb_array_length(q.options) as n
             from daily_set_items i join daily_sets s on s.id = i.set_id
             join questions q on q.id = i.question_id join passages p on p.id = q.passage_id
            where s.user_id = %s and s.set_date = %s and q.section = 'listening'
            order by i.position""", (conn.uid, day)).fetchall()
    assert [r["format"] for r in rows] == ["question-response"] * 3 + ["conversation"] * 3 + \
        ["talk"] * 3
    assert all(r["kind"] == "listening" and r["audio_id"] for r in rows)
    assert [r["n"] for r in rows[:3]] == [3, 3, 3] and rows[3]["n"] == 4
    # 應答題的音檔要唸出三個選項
    assert len(tts.calls[0]) == 4 and tts.calls[0][1].text.startswith("A. ")

    other = uuid.uuid4()
    conn.execute("insert into auth.users (id, email) values (%s, 'o2@t')", (other,))
    conn.commit()
    try:
        conn.execute("set role authenticated")
        as_user(conn, conn.uid)
        clip = conn.execute("select * from get_audio(%s)", (rows[0]["audio_id"],)).fetchone()
        assert clip["mime"] == "audio/mpeg"
        import base64
        assert base64.b64decode(clip["data_b64"]) == b"ID3-fake-mp3"
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("select data from audio_clips")
        conn.rollback()
        conn.execute("set role authenticated")
        as_user(conn, other)
        assert conn.execute("select * from get_audio(%s)",
                            (rows[0]["audio_id"],)).fetchone() is None
        conn.rollback()

        # 三選一的應答題可以作答
        conn.execute("set role authenticated")
        as_user(conn, conn.uid)
        qr = items[0]
        r = submit(conn, qr, qr["answer_index"])
        assert r["is_correct"] is True
        conn.commit()
    finally:
        conn.execute("reset role")
        conn.execute("delete from auth.users where id = %s", (other,))
        conn.commit()


def test_falls_back_to_v1_without_migration(conn, monkeypatch):
    monkeypatch.setattr(dbmod, "has_v2", lambda c: False)
    day = date(2026, 10, 15)
    msg = generate_for_user(conn, FakeLLM(), "fake", user_row(conn), day, False,
                            random.Random(6), FakeTTS())
    assert "0 listening + 10 usage + 4 reading" in msg
    tags = {i["skill_tag"] for i in set_items(conn, day)}
    assert not any(t.startswith("listening:") for t in tags)
    assert not tags & {"reading:text-completion", "reading:sentence-insertion",
                       "reading:multi-passage", "reading:graphic"}


def test_prune_audio_keeps_reviewed_clips(conn):
    day = date(2026, 10, 16)
    generate_for_user(conn, FakeLLM(), "fake", user_row(conn), day, False, random.Random(7),
                      FakeTTS())
    items = set_items(conn, day)
    as_user(conn, conn.uid)
    submit(conn, items[0], (items[0]["answer_index"] + 1) % 3)   # 答錯 → 進錯題複習
    conn.execute("reset role")
    conn.execute("update audio_clips set created_at = now() - interval '90 days' "
                 "where user_id = %s", (conn.uid,))
    deleted = dbmod.prune_audio(conn, conn.uid)
    assert deleted == 4   # 5 段音檔，留下錯題那段
    left = conn.execute("select count(*) as n from audio_clips where user_id = %s",
                        (conn.uid,)).fetchone()["n"]
    assert left == 1
