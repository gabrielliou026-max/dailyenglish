-- DailyEnglish v2：聽力（Kokoro 音檔）與閱讀新題型
-- 在 Supabase Dashboard → SQL Editor 貼上整份執行一次即可（需先執行過 0001）。
-- 可以重複執行：每個步驟都會先檢查是否已存在。

-- ---------------------------------------------------------------------------
-- 題目：聽力「應答」只有 3 個選項，所以選項改為 3–4 個
-- ---------------------------------------------------------------------------
alter table public.questions drop constraint if exists questions_options_check;
alter table public.questions drop constraint if exists questions_answer_index_check;
alter table public.questions drop constraint if exists questions_distractor_notes_zh_check;
alter table public.questions drop constraint if exists questions_option_count;
alter table public.questions add constraint questions_option_count check (
  jsonb_array_length(options) between 3 and 4
  and jsonb_array_length(distractor_notes_zh) = jsonb_array_length(options)
  and answer_index >= 0 and answer_index < jsonb_array_length(options));

-- ---------------------------------------------------------------------------
-- 音檔：存在資料庫（bytea），不需要另外設定 Storage 或金鑰
-- 每天約 1 MB；出題程式會自動清掉 60 天前、且不在錯題複習中的音檔
-- ---------------------------------------------------------------------------
create table if not exists public.audio_clips (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references auth.users (id) on delete cascade,
  mime         text not null default 'audio/mpeg',
  duration_ms  int,
  data         bytea not null,
  created_at   timestamptz not null default now()
);
alter table public.audio_clips enable row level security;
-- 前端不直接讀這張表，一律透過 get_audio()

-- 文章／聽力稿
alter table public.passages add column if not exists kind text not null default 'reading';
alter table public.passages drop constraint if exists passages_kind_check;
alter table public.passages add constraint passages_kind_check
  check (kind in ('reading', 'listening'));
alter table public.passages add column if not exists format text;   -- 例如 conversation、text-completion
alter table public.passages add column if not exists script jsonb;  -- 聽力台詞 [{speaker, gender, text}]
alter table public.passages add column if not exists audio_id uuid
  references public.audio_clips (id) on delete set null;

-- ---------------------------------------------------------------------------
-- 技能：啟用聽力，新增閱讀題型
-- ---------------------------------------------------------------------------
update public.skills set active = true where section = 'listening';

insert into public.skills (tag, section, label_zh, active, sort) values
  ('reading:text-completion',   'reading', '閱讀：短文填空',     true, 56),
  ('reading:sentence-insertion','reading', '閱讀：篇章結構',     true, 57),
  ('reading:multi-passage',     'reading', '閱讀：多篇整合',     true, 58),
  ('reading:graphic',           'reading', '閱讀：表格與圖表',   true, 59)
on conflict (tag) do nothing;

-- ---------------------------------------------------------------------------
-- RPC：取得音檔（base64），只能取自己的
-- ---------------------------------------------------------------------------
create or replace function public.get_audio(p_id uuid)
returns table (mime text, data_b64 text)
language sql stable security definer set search_path = public as $$
  select c.mime, encode(c.data, 'base64')
    from audio_clips c
   where c.id = p_id and c.user_id = auth.uid()
$$;

revoke execute on function public.get_audio(uuid) from public, anon;
grant execute on function public.get_audio(uuid) to authenticated;
