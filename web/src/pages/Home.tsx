import { useEffect, useState } from 'react'
import type { View } from '../App'
import { supabase, todayIn } from '../lib/supabase'

interface SetRow {
  id: string
  set_date: string
  completed_at: string | null
  items: { count: number }[]
  attempts: { count: number }[]
}

function shiftDate(iso: string, days: number): string {
  const d = new Date(iso + 'T00:00:00Z')
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

function streak(rows: SetRow[], today: string): number {
  const done = new Set(rows.filter((r) => r.completed_at).map((r) => r.set_date))
  let day = done.has(today) ? today : shiftDate(today, -1)
  let n = 0
  while (done.has(day)) {
    n++
    day = shiftDate(day, -1)
  }
  return n
}

export default function Home({ go }: { go: (v: View) => void }) {
  const [rows, setRows] = useState<SetRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const today = todayIn()

  useEffect(() => {
    supabase
      .from('daily_sets')
      .select('id,set_date,completed_at,items:daily_set_items(count),attempts(count)')
      .order('set_date', { ascending: false })
      .limit(60)
      .then(({ data, error }) => {
        if (error) setError(error.message)
        else setRows(data as unknown as SetRow[])
      })
  }, [])

  if (error) return <main className="page"><p className="error">{error}</p></main>
  if (!rows) return <main className="page center">載入中…</main>

  const current = rows.find((r) => r.set_date === today)
  const unfinished = rows.filter((r) => r.set_date !== today && !r.completed_at).slice(0, 3)

  return (
    <main className="page">
      <header className="topbar">
        <h1>DailyEnglish</h1>
        <button className="link" onClick={() => supabase.auth.signOut()}>登出</button>
      </header>

      <section className="card">
        <p className="muted">{today}</p>
        {current ? (
          <SetCard row={current} title="今日題組" go={go} />
        ) : (
          <p>今日題組尚未產生。題目每天清晨自動產生，若一直沒出現，請到 GitHub Actions 檢查執行紀錄。</p>
        )}
        <p className="streak">連續完成 <strong>{streak(rows, today)}</strong> 天</p>
      </section>

      {unfinished.length > 0 && (
        <section className="card">
          <h2>未完成的題組</h2>
          {unfinished.map((r) => <SetCard key={r.id} row={r} title={r.set_date} go={go} />)}
        </section>
      )}

      <button className="secondary wide" onClick={() => go({ name: 'stats' })}>學習分析</button>
    </main>
  )
}

function SetCard({ row, title, go }: { row: SetRow; title: string; go: (v: View) => void }) {
  const total = row.items[0]?.count ?? 0
  const done = row.attempts[0]?.count ?? 0
  const label = row.completed_at ? '查看結果' : done > 0 ? '繼續作答' : '開始'
  return (
    <div className="setcard">
      <div>
        <h2>{title}</h2>
        <p className="muted">{done} / {total} 題{row.completed_at ? '・已完成' : ''}</p>
      </div>
      <button className="primary" onClick={() => go({ name: 'quiz', setId: row.id })}>{label}</button>
    </div>
  )
}
