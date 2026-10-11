-- DailyEnglish v1 schema
-- 在 Supabase Dashboard → SQL Editor 貼上整份執行一次即可。

-- ---------------------------------------------------------------------------
-- 使用者設定
-- ---------------------------------------------------------------------------
create table public.profiles (
  user_id     uuid primary key references auth.users (id) on delete cascade,
  base_level  int  not null default 805,   -- 初始程度（多益分數尺度）
  goal_level  int  not null default 900,   -- 目標程度
  timezone    text not null default 'Asia/Taipei',
  created_at  timestamptz not null default now()
);

create function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (user_id) values (new.id) on conflict do nothing;
  return new;
end $$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- 若先建立使用者才執行本檔，補建 profile
insert into public.profiles (user_id) select id from auth.users on conflict do nothing;

-- ---------------------------------------------------------------------------
-- 技能分類（skill tag）
-- ---------------------------------------------------------------------------
create table public.skills (
  tag       text primary key,
  section   text not null check (section in ('listening', 'usage', 'reading')),
  label_zh  text not null,
  active    boolean not null default true,
  sort      int not null default 0
);

insert into public.skills (tag, section, label_zh, active, sort) values
  ('grammar:verb-tense',             'usage',     '時態',               true,  10),
  ('grammar:subject-verb',           'usage',     '主詞動詞一致',       true,  11),
  ('grammar:passive',                'usage',     '被動語態',           true,  12),
  ('grammar:conditional-subjunctive','usage',     '條件句與假設語氣',   true,  13),
  ('grammar:relative-clause',        'usage',     '關係子句',           true,  14),
  ('grammar:participle',             'usage',     '分詞與分詞構句',     true,  15),
  ('grammar:gerund-infinitive',      'usage',     '動名詞與不定詞',     true,  16),
  ('grammar:conjunction',            'usage',     '連接詞與轉折語',     true,  17),
  ('grammar:preposition',            'usage',     '介系詞',             true,  18),
  ('grammar:pronoun-determiner',     'usage',     '代名詞與限定詞',     true,  19),
  ('grammar:comparison',             'usage',     '比較句型',           true,  20),
  ('grammar:word-form',              'usage',     '詞性變化',           true,  21),
  ('grammar:inversion-emphasis',     'usage',     '倒裝與強調',         true,  22),
  ('vocab:business',                 'usage',     '字彙：商務職場',     true,  30),
  ('vocab:finance',                  'usage',     '字彙：財經',         true,  31),
  ('vocab:travel-logistics',         'usage',     '字彙：旅遊與物流',   true,  32),
  ('vocab:news-society',             'usage',     '字彙：新聞時事',     true,  33),
  ('vocab:government-defense',       'usage',     '字彙：政府與國防',   true,  34),
  ('vocab:science-tech',             'usage',     '字彙：科技',         true,  35),
  ('vocab:collocation',              'usage',     '搭配詞',             true,  36),
  ('vocab:phrasal-idiom',            'usage',     '片語動詞與慣用語',   true,  37),
  ('reading:main-idea',              'reading',   '閱讀：主旨',         true,  50),
  ('reading:detail',                 'reading',   '閱讀：細節',         true,  51),
  ('reading:inference',              'reading',   '閱讀：推論',         true,  52),
  ('reading:vocab-in-context',       'reading',   '閱讀：字義推敲',     true,  53),
  ('reading:purpose-tone',           'reading',   '閱讀：目的與語氣',   true,  54),
  ('reading:not-true',               'reading',   '閱讀：NOT／EXCEPT', true,  55),
  -- 聽力於 v2 啟用
  ('listening:question-response',    'listening', '聽力：應答',         false, 70),
  ('listening:conversation',         'listening', '聽力：對話',         false, 71),
  ('listening:talk',                 'listening', '聽力：獨白',         false, 72),
  ('listening:inference',            'listening', '聽力：推論',         false, 73);

-- ---------------------------------------------------------------------------
-- 題目
-- ---------------------------------------------------------------------------
create table public.passages (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references auth.users (id) on delete cascade,
  exam_style  text not null check (exam_style in ('toeic', 'flpt')),
  genre       text not null,
  title       text,
  body        text not null,
  audio_path  text,                         -- v2：聽力音檔
  created_at  timestamptz not null default now()
);

create table public.questions (
  id                  uuid primary key default gen_random_uuid(),
  user_id             uuid not null references auth.users (id) on delete cascade,
  created_on          date not null,
  exam_style          text not null check (exam_style in ('toeic', 'flpt')),
  section             text not null check (section in ('listening', 'usage', 'reading')),
  skill_tag           text not null references public.skills (tag),
  focus               text not null,        -- 具體考點，例如 "reimburse" 或 "had + p.p. 假設"
  difficulty          int  not null,        -- 多益分數尺度
  passage_id          uuid references public.passages (id) on delete cascade,
  stem                text not null,
  options             jsonb not null check (jsonb_array_length(options) = 4),
  answer_index        smallint not null check (answer_index between 0 and 3),
  explanation_zh      text not null,
  distractor_notes_zh jsonb not null check (jsonb_array_length(distractor_notes_zh) = 4),
  model               text,
  status              text not null default 'active' check (status in ('active', 'flagged')),
  flag_note           text,
  created_at          timestamptz not null default now()
);
create index questions_user_created on public.questions (user_id, created_at desc);

-- ---------------------------------------------------------------------------
-- 每日題組
-- ---------------------------------------------------------------------------
create table public.daily_sets (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users (id) on delete cascade,
  set_date      date not null,
  created_at    timestamptz not null default now(),
  completed_at  timestamptz,
  unique (user_id, set_date)
);

create table public.daily_set_items (
  set_id       uuid not null references public.daily_sets (id) on delete cascade,
  position     smallint not null,
  question_id  uuid not null references public.questions (id) on delete cascade,
  is_review    boolean not null default false,
  primary key (set_id, position),
  unique (set_id, question_id)
);

-- ---------------------------------------------------------------------------
-- 作答紀錄與統計
-- ---------------------------------------------------------------------------
create table public.attempts (
  id            bigint generated always as identity primary key,
  user_id       uuid not null references auth.users (id) on delete cascade,
  set_id        uuid not null references public.daily_sets (id) on delete cascade,
  question_id   uuid not null references public.questions (id) on delete cascade,
  chosen_index  smallint not null check (chosen_index between 0 and 3),
  is_correct    boolean not null,
  time_ms       int,
  is_review     boolean not null default false,
  rating_before real,
  rating_after  real,
  answered_at   timestamptz not null default now(),
  unique (set_id, question_id)
);
create index attempts_user_time on public.attempts (user_id, answered_at desc);

create table public.skill_stats (
  user_id       uuid not null references auth.users (id) on delete cascade,
  skill_tag     text not null references public.skills (tag),
  rating        real not null,
  n_attempts    int  not null default 0,
  n_correct     int  not null default 0,
  ema_accuracy  real,                       -- 近期答對率（指數移動平均）
  avg_time_ms   real,
  last_seen     timestamptz,
  primary key (user_id, skill_tag)
);

-- 錯題間隔複習：1 → 3 → 7 → 14 → 30 天，30 天那次答對即畢業
create table public.review_queue (
  user_id        uuid not null references auth.users (id) on delete cascade,
  question_id    uuid not null references public.questions (id) on delete cascade,
  interval_days  int  not null default 1,
  due_on         date not null,
  lapses         int  not null default 1,
  primary key (user_id, question_id)
);

-- 出題紀錄（含 token 用量，用來估算費用）
create table public.generation_runs (
  id             bigint generated always as identity primary key,
  user_id        uuid references auth.users (id) on delete cascade,
  set_date       date,
  started_at     timestamptz not null default now(),
  finished_at    timestamptz,
  status         text not null default 'running',
  model          text,
  input_tokens   int not null default 0,
  output_tokens  int not null default 0,
  n_accepted     int not null default 0,
  n_rejected     int not null default 0,
  error          text
);

-- ---------------------------------------------------------------------------
-- Row Level Security：前端只能讀自己的資料，寫入一律透過 RPC
-- ---------------------------------------------------------------------------
alter table public.profiles        enable row level security;
alter table public.skills          enable row level security;
alter table public.passages        enable row level security;
alter table public.questions       enable row level security;
alter table public.daily_sets      enable row level security;
alter table public.daily_set_items enable row level security;
alter table public.attempts        enable row level security;
alter table public.skill_stats     enable row level security;
alter table public.review_queue    enable row level security;
alter table public.generation_runs enable row level security;

create policy "own profile"   on public.profiles        for select to authenticated using (user_id = auth.uid());
create policy "skills"        on public.skills          for select to authenticated using (true);
create policy "own passages"  on public.passages        for select to authenticated using (user_id = auth.uid());
create policy "own questions" on public.questions       for select to authenticated using (user_id = auth.uid());
create policy "own sets"      on public.daily_sets      for select to authenticated using (user_id = auth.uid());
create policy "own set items" on public.daily_set_items for select to authenticated
  using (exists (select 1 from public.daily_sets s where s.id = set_id and s.user_id = auth.uid()));
create policy "own attempts"  on public.attempts        for select to authenticated using (user_id = auth.uid());
create policy "own stats"     on public.skill_stats     for select to authenticated using (user_id = auth.uid());
create policy "own reviews"   on public.review_queue    for select to authenticated using (user_id = auth.uid());
create policy "own runs"      on public.generation_runs for select to authenticated using (user_id = auth.uid());

grant select on public.profiles, public.skills, public.passages, public.questions,
  public.daily_sets, public.daily_set_items, public.attempts, public.skill_stats,
  public.review_queue, public.generation_runs to authenticated;

-- ---------------------------------------------------------------------------
-- RPC：送出答案，更新能力值與錯題複習
-- ---------------------------------------------------------------------------
create function public.submit_attempt(
  p_set_id uuid, p_question_id uuid, p_chosen smallint, p_time_ms int
) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  v_uid       uuid := auth.uid();
  v_profile   profiles%rowtype;
  v_q         questions%rowtype;
  v_review    boolean;
  v_correct   boolean;
  v_today     date;
  v_stat      skill_stats%rowtype;
  v_expected  real;
  v_k         real;
  v_before    real;
  v_after     real;
  v_interval  int;
  v_existing  attempts%rowtype;
begin
  if v_uid is null then
    raise exception 'not authenticated';
  end if;

  select i.is_review into v_review
    from daily_set_items i join daily_sets s on s.id = i.set_id
   where i.set_id = p_set_id and i.question_id = p_question_id and s.user_id = v_uid;
  if not found then
    raise exception 'question not in this set';
  end if;

  select * into v_q from questions where id = p_question_id and user_id = v_uid;

  -- 重複送出時回傳第一次的結果，不重算
  select * into v_existing from attempts where set_id = p_set_id and question_id = p_question_id;
  if found then
    return jsonb_build_object(
      'is_correct', v_existing.is_correct, 'answer_index', v_q.answer_index,
      'rating_before', v_existing.rating_before, 'rating_after', v_existing.rating_after,
      'duplicate', true);
  end if;

  select * into v_profile from profiles where user_id = v_uid;
  v_today   := (now() at time zone coalesce(v_profile.timezone, 'Asia/Taipei'))::date;
  v_correct := p_chosen = v_q.answer_index;

  -- 能力值（Elo 變形）：只用新題、且題目未被回報有問題時更新。
  -- 預期答對率含四選一猜題下限 0.25。
  if not v_review and v_q.status = 'active' then
    insert into skill_stats (user_id, skill_tag, rating)
    values (v_uid, v_q.skill_tag, coalesce(v_profile.base_level, 805))
    on conflict do nothing;

    select * into v_stat from skill_stats
     where user_id = v_uid and skill_tag = v_q.skill_tag for update;

    v_before   := v_stat.rating;
    v_expected := 0.25 + 0.75 / (1 + power(10, (v_q.difficulty - v_before) / 150.0));
    v_k        := case when v_stat.n_attempts < 10 then 48
                       when v_stat.n_attempts < 30 then 32
                       else 20 end;
    v_after    := least(990, greatest(200, v_before + v_k * ((v_correct::int) - v_expected)));

    update skill_stats set
      rating       = v_after,
      n_attempts   = n_attempts + 1,
      n_correct    = n_correct + v_correct::int,
      ema_accuracy = case when ema_accuracy is null then v_correct::int
                          else 0.8 * ema_accuracy + 0.2 * v_correct::int end,
      avg_time_ms  = case when p_time_ms is null then avg_time_ms
                          when avg_time_ms is null then p_time_ms
                          else 0.8 * avg_time_ms + 0.2 * p_time_ms end,
      last_seen    = now()
    where user_id = v_uid and skill_tag = v_q.skill_tag;
  end if;

  insert into attempts (user_id, set_id, question_id, chosen_index, is_correct, time_ms,
                        is_review, rating_before, rating_after)
  values (v_uid, p_set_id, p_question_id, p_chosen, v_correct, p_time_ms,
          v_review, v_before, v_after);

  -- 錯題複習排程
  if v_q.status = 'active' then
    if not v_correct then
      insert into review_queue (user_id, question_id, interval_days, due_on, lapses)
      values (v_uid, p_question_id, 1, v_today + 1, 1)
      on conflict (user_id, question_id) do update
        set interval_days = 1, due_on = v_today + 1, lapses = review_queue.lapses + 1;
    elsif v_review then
      select interval_days into v_interval from review_queue
       where user_id = v_uid and question_id = p_question_id;
      if v_interval is null then
        null;
      elsif v_interval >= 30 then
        delete from review_queue where user_id = v_uid and question_id = p_question_id;
      else
        v_interval := case when v_interval < 3 then 3
                           when v_interval < 7 then 7
                           when v_interval < 14 then 14
                           else 30 end;
        update review_queue set interval_days = v_interval, due_on = v_today + v_interval
         where user_id = v_uid and question_id = p_question_id;
      end if;
    end if;
  end if;

  -- 全部做完就標記完成
  if (select count(*) from attempts where set_id = p_set_id)
     = (select count(*) from daily_set_items where set_id = p_set_id) then
    update daily_sets set completed_at = now() where id = p_set_id and completed_at is null;
  end if;

  return jsonb_build_object(
    'is_correct', v_correct, 'answer_index', v_q.answer_index,
    'rating_before', v_before, 'rating_after', v_after, 'duplicate', false);
end $$;

-- RPC：回報題目有問題（之後不再計分、也不進複習）
create function public.flag_question(p_question_id uuid, p_note text)
returns void
language plpgsql security definer set search_path = public as $$
begin
  if auth.uid() is null then
    raise exception 'not authenticated';
  end if;
  update questions set status = 'flagged', flag_note = p_note
   where id = p_question_id and user_id = auth.uid();
  delete from review_queue where question_id = p_question_id and user_id = auth.uid();
end $$;

revoke execute on function public.submit_attempt(uuid, uuid, smallint, int) from public, anon;
revoke execute on function public.flag_question(uuid, text) from public, anon;
grant execute on function public.submit_attempt(uuid, uuid, smallint, int) to authenticated;
grant execute on function public.flag_question(uuid, text) to authenticated;
revoke execute on function public.handle_new_user() from public, anon, authenticated;
