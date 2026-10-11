import { useEffect, useState } from 'react'
import type { View } from '../App'
import { SkillStat, supabase, TIMEZONE } from '../lib/supabase'

interface RecentAttempt {
  answered_at: string
  is_correct: boolean
  question: { skill_tag: string; focus: string; section: string }
}

interface Run {
  set_date: string
  status: string
  model: string
  input_tokens: number
  output_tokens: number
  n_accepted: number
  n_rejected: number
  error: string | null
}

const dayFmt = new Intl.DateTimeFormat('en-CA', { timeZone: TIMEZONE })

export default function Stats({ labels, go }: { labels: Record<string, string>; go: (v: View) => void }) {
  const [stats, setStats] = useState<SkillStat[] | null>(null)
  const [recent, setRecent] = useState<RecentAttempt[]>([])
  const [runs, setRuns] = useState<Run[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const since = new Date(Date.now() - 14 * 86400_000).toISOString()
    Promise.all([
      supabase.from('skill_stats').select('*').order('rating'),
      supabase.from('attempts').select('answered_at,is_correct,question:questions(skill_tag,focus,section)')
        .gte('answered_at', since).order('answered_at', { ascending: false }),
      supabase.from('generation_runs').select('*').order('started_at', { ascending: false }).limit(7),
    ]).then(([s, a, r]) => {
      const e = s.error ?? a.error ?? r.error
      if (e) return setError(e.message)
      setStats(s.data as SkillStat[])
      setRecent(a.data as unknown as RecentAttempt[])
      setRuns(r.data as Run[])
    })
  }, [])

  if (error) return <main className="page"><p className="error">{error}</p></main>
  if (!stats) return <main className="page center">載入中…</main>

  const measured = stats.filter((s) => s.n_attempts >= 3)
  const overall = measured.length
    ? Math.round(measured.reduce((t, s) => t + s.rating * s.n_attempts, 0) /
                 measured.reduce((t, s) => t + s.n_attempts, 0))
    : null

  const sectionOf = (tag: string) => (tag.startsWith('reading:') ? '閱讀'
    : tag.startsWith('listening:') ? '聽力' : '用法')
  const bySection: Record<string, { sum: number; n: number }> = {}
  for (const s of measured) {
    const k = sectionOf(s.skill_tag)
    bySection[k] ??= { sum: 0, n: 0 }
    bySection[k].sum += s.rating * s.n_attempts
    bySection[k].n += s.n_attempts
  }

  const days: Record<string, { n: number; ok: number }> = {}
  for (const a of recent) {
    const d = dayFmt.format(new Date(a.answered_at))
    days[d] ??= { n: 0, ok: 0 }
    days[d].n++
    if (a.is_correct) days[d].ok++
  }

  const focusMiss: Record<string, { tag: string; n: number }> = {}
  for (const a of recent) {
    if (a.is_correct) continue
    focusMiss[a.question.focus] ??= { tag: a.question.skill_tag, n: 0 }
    focusMiss[a.question.focus].n++
  }

  return (
    <main className="page">
      <header className="topbar">
        <button className="link" onClick={() => go({ name: 'home' })}>← 首頁</button>
        <h1>學習分析</h1>
      </header>

      <section className="card center-text">
        <p className="muted">粗估程度（多益分數尺度）</p>
        <p className="score">{overall ?? '—'}</p>
        <p className="muted small">依各技能能力值加權平均，僅供追蹤趨勢，非官方換算。每項技能至少作答 3 題才列入。</p>
        {Object.keys(bySection).length > 0 && (
          <p>{Object.entries(bySection).map(([k, v]) => `${k} ${Math.round(v.sum / v.n)}`).join('・')}</p>
        )}
      </section>

      <section className="card">
        <h2>各技能（由弱到強）</h2>
        {stats.length === 0 ? <p className="muted">還沒有作答紀錄。</p> : (
          <table className="table">
            <thead><tr><th>技能</th><th>能力值</th><th>答對</th><th>平均秒數</th></tr></thead>
            <tbody>
              {stats.map((s, i) => (
                <tr key={s.skill_tag} className={i < 3 && s.n_attempts >= 3 ? 'weak' : ''}>
                  <td>{labels[s.skill_tag] ?? s.skill_tag}</td>
                  <td>{Math.round(s.rating)}</td>
                  <td>{s.n_correct}/{s.n_attempts}</td>
                  <td>{s.avg_time_ms ? Math.round(s.avg_time_ms / 1000) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card">
        <h2>近 14 天</h2>
        {Object.keys(days).length === 0 ? <p className="muted">沒有紀錄。</p> : (
          <table className="table">
            <tbody>
              {Object.entries(days).map(([d, v]) => (
                <tr key={d}><td>{d.slice(5)}</td><td>{v.ok} / {v.n}</td><td>{Math.round((v.ok / v.n) * 100)}%</td></tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {Object.keys(focusMiss).length > 0 && (
        <section className="card">
          <h2>近期答錯的考點</h2>
          <ul className="plain">
            {Object.entries(focusMiss).sort((a, b) => b[1].n - a[1].n).slice(0, 20).map(([f, v]) => (
              <li key={f}><strong>{f}</strong> <span className="muted small">{labels[v.tag] ?? v.tag}{v.n > 1 ? `・${v.n} 次` : ''}</span></li>
            ))}
          </ul>
        </section>
      )}

      <section className="card">
        <h2>出題紀錄</h2>
        {runs.length === 0 ? <p className="muted">沒有紀錄。</p> : (
          <table className="table small">
            <thead><tr><th>日期</th><th>狀態</th><th>題數</th><th>tokens（入/出）</th></tr></thead>
            <tbody>
              {runs.map((r, i) => (
                <tr key={i} title={r.error ?? ''}>
                  <td>{r.set_date?.slice(5)}</td>
                  <td className={r.status === 'ok' ? 'ok' : 'bad'}>{r.status}</td>
                  <td>{r.n_accepted}（淘汰 {r.n_rejected}）</td>
                  <td>{(r.input_tokens / 1000).toFixed(1)}k / {(r.output_tokens / 1000).toFixed(1)}k</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </main>
  )
}
