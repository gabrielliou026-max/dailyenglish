import { createClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL as string | undefined
const key = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined

export const configured = Boolean(url && key)

export const supabase = createClient(url ?? 'http://localhost', key ?? 'missing', {
  auth: { persistSession: true, autoRefreshToken: true },
})

export type Section = 'listening' | 'usage' | 'reading'

export interface ScriptLine {
  speaker: string
  gender: 'f' | 'm'
  text: string
}

export interface Passage {
  id: string
  title: string | null
  body: string
  genre: string
  // v2（0002 migration 之後才有）
  kind?: 'reading' | 'listening'
  format?: string | null
  script?: ScriptLine[] | null
  audio_id?: string | null
}

export interface Question {
  id: string
  section: Section
  skill_tag: string
  focus: string
  difficulty: number
  exam_style: 'toeic' | 'flpt'
  stem: string
  options: string[]
  answer_index: number
  explanation_zh: string
  distractor_notes_zh: string[]
  status: 'active' | 'flagged'
  passage: Passage | null
}

export interface SetItem {
  position: number
  is_review: boolean
  question: Question
}

export interface DailySet {
  id: string
  set_date: string
  completed_at: string | null
}

export interface Attempt {
  question_id: string
  chosen_index: number
  is_correct: boolean
  time_ms: number | null
  is_review: boolean
  rating_before: number | null
  rating_after: number | null
  answered_at: string
}

export interface SubmitResult {
  is_correct: boolean
  answer_index: number
  rating_before: number | null
  rating_after: number | null
  duplicate: boolean
}

export interface SkillStat {
  skill_tag: string
  rating: number
  n_attempts: number
  n_correct: number
  ema_accuracy: number | null
  avg_time_ms: number | null
}

export const SECTION_LABEL: Record<Section, string> = {
  listening: '聽力',
  usage: '用法',
  reading: '閱讀',
}

export const TIMEZONE = 'Asia/Taipei'

export function todayIn(tz = TIMEZONE): string {
  // en-CA 格式即 YYYY-MM-DD
  return new Intl.DateTimeFormat('en-CA', { timeZone: tz }).format(new Date())
}

export async function loadSkillLabels(): Promise<Record<string, string>> {
  const { data, error } = await supabase.from('skills').select('tag,label_zh')
  if (error) throw error
  return Object.fromEntries((data ?? []).map((s) => [s.tag, s.label_zh]))
}

export const FORMAT_LABEL: Record<string, string> = {
  'question-response': '應答',
  conversation: '對話',
  talk: '獨白',
  single: '單篇閱讀',
  double: '雙篇閱讀',
  triple: '三篇閱讀',
  graphic: '表格與圖表',
  'text-completion': '短文填空',
}

// 音檔：透過 get_audio() 取回 base64，轉成 blob URL；同一段只抓一次
const audioCache = new Map<string, Promise<string>>()

export function audioUrl(id: string): Promise<string> {
  let p = audioCache.get(id)
  if (!p) {
    p = (async () => {
      const { data, error } = await supabase.rpc('get_audio', { p_id: id })
      if (error) throw error
      const row = (data as { mime: string; data_b64: string }[] | null)?.[0]
      if (!row) throw new Error('找不到音檔')
      const bin = atob(row.data_b64)
      const bytes = new Uint8Array(bin.length)
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
      return URL.createObjectURL(new Blob([bytes], { type: row.mime || 'audio/mpeg' }))
    })()
    p.catch(() => audioCache.delete(id))
    audioCache.set(id, p)
  }
  return p
}
