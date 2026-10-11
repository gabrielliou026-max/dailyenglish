import { useEffect, useMemo, useRef, useState } from 'react'
import type { View } from '../App'
import {
  Attempt, SECTION_LABEL, SetItem, SubmitResult, supabase,
} from '../lib/supabase'

const LETTERS = ['A', 'B', 'C', 'D']

const ITEM_SELECT = `position,is_review,question:questions(
  id,section,skill_tag,focus,difficulty,exam_style,stem,options,answer_index,
  explanation_zh,distractor_notes_zh,status,passage:passages(id,title,body,genre))`

// 複習題重新排列選項，避免記住位置；以題目 id 當種子，重新整理頁面順序也不變
function displayOrder(item: SetItem, setId: string): number[] {
  const order = [0, 1, 2, 3]
  if (!item.is_review) return order
  let h = 2166136261
  for (const c of setId + item.question.id) h = Math.imul(h ^ c.charCodeAt(0), 16777619)
  for (let i = 3; i > 0; i--) {
    h = Math.imul(h ^ (h >>> 15), 2246822507) >>> 0
    const j = h % (i + 1)
    ;[order[i], order[j]] = [order[j], order[i]]
  }
  return order
}

interface Props {
  setId: string
  labels: Record<string, string>
  go: (v: View) => void
}

export default function Quiz({ setId, labels, go }: Props) {
  const [items, setItems] = useState<SetItem[] | null>(null)
  const [attempts, setAttempts] = useState<Record<string, Attempt>>({})
  const [idx, setIdx] = useState(0)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([
      supabase.from('daily_set_items').select(ITEM_SELECT).eq('set_id', setId).order('position'),
      supabase.from('attempts').select('*').eq('set_id', setId),
    ]).then(([it, at]) => {
      if (it.error || at.error) {
        setError((it.error ?? at.error)!.message)
        return
      }
      const list = it.data as unknown as SetItem[]
      const map = Object.fromEntries((at.data as Attempt[]).map((a) => [a.question_id, a]))
      setItems(list)
      setAttempts(map)
      const first = list.findIndex((x) => !map[x.question.id])
      setIdx(first === -1 ? list.length : first)
    })
  }, [setId])

  if (error) return <main className="page"><p className="error">{error}</p></main>
  if (!items) return <main className="page center">載入中…</main>
  if (idx >= items.length) {
    return <Summary items={items} attempts={attempts} labels={labels} go={go} />
  }

  return (
    <QuestionView
      key={items[idx].question.id}
      setId={setId}
      item={items[idx]}
      index={idx}
      total={items.length}
      label={labels[items[idx].question.skill_tag] ?? items[idx].question.skill_tag}
      prior={attempts[items[idx].question.id]}
      onAnswered={(a) => setAttempts((m) => ({ ...m, [a.question_id]: a }))}
      onNext={() => setIdx(idx + 1)}
      onExit={() => go({ name: 'home' })}
    />
  )
}

interface QVProps {
  setId: string
  item: SetItem
  index: number
  total: number
  label: string
  prior?: Attempt
  onAnswered: (a: Attempt) => void
  onNext: () => void
  onExit: () => void
}

function QuestionView({ setId, item, index, total, label, prior, onAnswered, onNext, onExit }: QVProps) {
  const q = item.question
  const order = useMemo(() => displayOrder(item, setId), [item, setId])
  const started = useRef(Date.now())
  const [chosen, setChosen] = useState<number | null>(prior ? prior.chosen_index : null)
  const [result, setResult] = useState<SubmitResult | null>(
    prior ? { is_correct: prior.is_correct, answer_index: q.answer_index,
              rating_before: prior.rating_before, rating_after: prior.rating_after,
              duplicate: true } : null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showPassage, setShowPassage] = useState(true)
  const [flagged, setFlagged] = useState(q.status === 'flagged')

  async function answer(original: number) {
    if (result || busy) return
    setBusy(true)
    setChosen(original)
    const time_ms = Date.now() - started.current
    const { data, error } = await supabase.rpc('submit_attempt', {
      p_set_id: setId, p_question_id: q.id, p_chosen: original, p_time_ms: time_ms,
    })
    setBusy(false)
    if (error) {
      setError(error.message)
      setChosen(null)
      return
    }
    const r = data as SubmitResult
    setResult(r)
    onAnswered({
      question_id: q.id, chosen_index: original, is_correct: r.is_correct, time_ms,
      is_review: item.is_review, rating_before: r.rating_before, rating_after: r.rating_after,
      answered_at: new Date().toISOString(),
    })
  }

  async function flag() {
    const note = window.prompt('這題哪裡有問題？（例如：答案有爭議、兩個選項都對）')
    if (note === null) return
    const { error } = await supabase.rpc('flag_question', { p_question_id: q.id, p_note: note })
    if (error) setError(error.message)
    else setFlagged(true)
  }

  const delta = result?.rating_after != null && result.rating_before != null
    ? Math.round(result.rating_after - result.rating_before) : null

  return (
    <main className="page quiz">
      <header className="topbar">
        <button className="link" onClick={onExit}>← 首頁</button>
        <span className="muted">{index + 1} / {total}</span>
      </header>
      <div className="progress"><div style={{ width: `${(index / total) * 100}%` }} /></div>

      <div className="chips">
        <span className="chip">{item.is_review ? '錯題複習' : SECTION_LABEL[q.section]}</span>
        <span className="chip">{label}</span>
        <span className="chip muted">{q.exam_style === 'toeic' ? 'TOEIC' : 'FLPT'}</span>
      </div>

      {q.passage && (
        <section className="card passage">
          <button className="link" onClick={() => setShowPassage(!showPassage)}>
            {showPassage ? '收合文章 ▲' : '展開文章 ▼'}
          </button>
          {showPassage && (
            <>
              {q.passage.title && <h2>{q.passage.title}</h2>}
              {q.passage.body.split(/\n\s*\n/).map((p, i) => <p key={i}>{p}</p>)}
            </>
          )}
        </section>
      )}

      <p className="stem">{q.stem}</p>

      <div className="options">
        {order.map((orig, pos) => {
          let cls = 'option'
          if (result) {
            if (orig === result.answer_index) cls += ' correct'
            else if (orig === chosen) cls += ' wrong'
            else cls += ' dim'
          } else if (orig === chosen) cls += ' pending'
          return (
            <button key={orig} className={cls} onClick={() => answer(orig)} disabled={!!result || busy}>
              <span className="letter">{LETTERS[pos]}</span>
              <span>{q.options[orig]}</span>
            </button>
          )
        })}
      </div>

      {error && <p className="error">{error}</p>}

      {result && (
        <section className="card feedback">
          <p className={result.is_correct ? 'ok' : 'bad'}>{result.is_correct ? '答對了' : '答錯了'}</p>
          {delta !== null && (
            <p className="muted small">
              {label}：{Math.round(result.rating_before!)} → {Math.round(result.rating_after!)}（{delta >= 0 ? '+' : ''}{delta}）
            </p>
          )}
          <p>{q.explanation_zh}</p>
          <ul className="notes">
            {order.map((orig, pos) => (
              <li key={orig} className={orig === result.answer_index ? 'ok' : ''}>
                <strong>{LETTERS[pos]}.</strong> {q.distractor_notes_zh[orig]}
              </li>
            ))}
          </ul>
          <p className="muted small">考點：{q.focus}・難度約 {q.difficulty}</p>
          <div className="row">
            <button className="secondary" onClick={flag} disabled={flagged}>
              {flagged ? '已回報' : '回報題目有問題'}
            </button>
            <button className="primary" onClick={onNext}>{index + 1 === total ? '看結果' : '下一題'}</button>
          </div>
        </section>
      )}
    </main>
  )
}

function Summary({ items, attempts, labels, go }: {
  items: SetItem[]
  attempts: Record<string, Attempt>
  labels: Record<string, string>
  go: (v: View) => void
}) {
  const answered = items.filter((i) => attempts[i.question.id])
  const correct = answered.filter((i) => attempts[i.question.id].is_correct)
  const groups: Record<string, { n: number; ok: number }> = {}
  const deltas: Record<string, number> = {}
  for (const i of answered) {
    const a = attempts[i.question.id]
    const key = i.is_review ? '錯題複習' : SECTION_LABEL[i.question.section]
    groups[key] ??= { n: 0, ok: 0 }
    groups[key].n++
    if (a.is_correct) groups[key].ok++
    if (a.rating_after != null && a.rating_before != null) {
      deltas[i.question.skill_tag] = (deltas[i.question.skill_tag] ?? 0) + a.rating_after - a.rating_before
    }
  }
  const wrong = answered.filter((i) => !attempts[i.question.id].is_correct)
  const minutes = Math.round(answered.reduce((s, i) => s + (attempts[i.question.id].time_ms ?? 0), 0) / 60000)

  return (
    <main className="page">
      <header className="topbar">
        <button className="link" onClick={() => go({ name: 'home' })}>← 首頁</button>
      </header>
      <section className="card center-text">
        <p className="muted">本次結果</p>
        <p className="score">{correct.length} / {answered.length}</p>
        <p className="muted">約 {minutes} 分鐘</p>
      </section>

      <section className="card">
        <h2>各區答對率</h2>
        <table className="table">
          <tbody>
            {Object.entries(groups).map(([k, g]) => (
              <tr key={k}><td>{k}</td><td>{g.ok} / {g.n}</td><td>{Math.round((g.ok / g.n) * 100)}%</td></tr>
            ))}
          </tbody>
        </table>
      </section>

      {Object.keys(deltas).length > 0 && (
        <section className="card">
          <h2>能力值變化</h2>
          <table className="table">
            <tbody>
              {Object.entries(deltas).sort((a, b) => a[1] - b[1]).map(([tag, d]) => (
                <tr key={tag}><td>{labels[tag] ?? tag}</td>
                  <td className={d >= 0 ? 'ok' : 'bad'}>{d >= 0 ? '+' : ''}{Math.round(d)}</td></tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {wrong.length > 0 && (
        <section className="card">
          <h2>答錯的題目</h2>
          <p className="muted small">這些題目會在之後的「錯題複習」再出現。</p>
          <ul className="wronglist">
            {wrong.map((i) => (
              <li key={i.question.id}>
                <p className="small muted">{labels[i.question.skill_tag] ?? i.question.skill_tag}・{i.question.focus}</p>
                <p>{i.question.stem}</p>
                <p className="ok small">正解：{i.question.options[i.question.answer_index]}</p>
              </li>
            ))}
          </ul>
        </section>
      )}

      <button className="secondary wide" onClick={() => go({ name: 'stats' })}>學習分析</button>
    </main>
  )
}
