import { useEffect, useRef, useState } from 'react'
import { audioUrl, Passage } from '../lib/supabase'

// ---------------------------------------------------------------------------
// 閱讀：段落、[Document 1] 標題、純文字表格（| 分隔）、[1] 空格標記
// ---------------------------------------------------------------------------

function withBlanks(text: string) {
  return text.split(/(\[\d+\])/).map((seg, i) =>
    /^\[\d+\]$/.test(seg) ? <span key={i} className="blank">{seg}</span> : seg)
}

function Block({ text }: { text: string }) {
  const lines = text.split('\n')
  const rows = lines.filter((l) => l.includes('|'))
  if (rows.length >= 2) {
    const out: JSX.Element[] = []
    const table: string[][] = []
    lines.forEach((l, i) => {
      if (!l.includes('|')) {
        if (l.trim()) out.push(<p key={`p${i}`}>{withBlanks(l)}</p>)
        return
      }
      const cells = l.replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|').map((c) => c.trim())
      if (cells.every((c) => c === '' || /^:?-{2,}:?$/.test(c))) return
      table.push(cells)
    })
    return (
      <>
        {out}
        <div className="tablewrap">
          <table className="datatable">
            <tbody>
              {table.map((r, ri) => (
                <tr key={ri}>{r.map((c, ci) => ri === 0
                  ? <th key={ci}>{withBlanks(c)}</th>
                  : <td key={ci}>{withBlanks(c)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      </>
    )
  }
  if (/^\[Document \d+\]$/.test(text.trim())) return <h3 className="doctitle">{text.trim()}</h3>
  const m = text.match(/^(\[Document \d+\])\n([\s\S]*)$/)
  if (m) return <><h3 className="doctitle">{m[1]}</h3><Block text={m[2]} /></>
  return <p className="preline">{withBlanks(text)}</p>
}

export function PassageBody({ body }: { body: string }) {
  return <>{body.split(/\n\s*\n/).filter((p) => p.trim()).map((p, i) => <Block key={i} text={p.trim()} />)}</>
}

// ---------------------------------------------------------------------------
// 聽力：播放鍵（作答前最多播 2 次）＋作答後的文字稿
// ---------------------------------------------------------------------------

export const MAX_PLAYS = 2

function playsKey(setId: string, passageId: string) {
  return `plays:${setId}:${passageId}`
}

function readPlays(key: string): number {
  try { return Number(localStorage.getItem(key)) || 0 } catch { return 0 }
}

export function ListeningPlayer({ setId, passage, unlimited }: {
  setId: string
  passage: Passage
  unlimited: boolean
}) {
  const key = playsKey(setId, passage.id)
  const [plays, setPlays] = useState(() => readPlays(key))
  const [playing, setPlaying] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const audio = useRef<HTMLAudioElement | null>(null)

  useEffect(() => () => { audio.current?.pause() }, [])

  if (!passage.audio_id) {
    return <p className="muted small">這段沒有音檔，可以直接看下方文字稿作答。</p>
  }

  const left = MAX_PLAYS - plays
  const canPlay = unlimited || left > 0

  async function toggle() {
    if (playing) {
      audio.current?.pause()
      setPlaying(false)
      return
    }
    if (!canPlay) return
    setError(null)
    setLoading(true)
    try {
      const url = await audioUrl(passage.audio_id!)
      if (!audio.current) {
        audio.current = new Audio(url)
        audio.current.onended = () => setPlaying(false)
        audio.current.onpause = () => setPlaying(false)
      }
      audio.current.currentTime = 0
      await audio.current.play()
      setPlaying(true)
      if (!unlimited) {
        const n = plays + 1
        setPlays(n)
        try { localStorage.setItem(key, String(n)) } catch { /* 無痕模式等 */ }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '音檔載入失敗')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="player">
      <button className="primary" onClick={toggle} disabled={loading || (!playing && !canPlay)}>
        {loading ? '載入中…' : playing ? '■ 停止' : '▶ 播放'}
      </button>
      <span className="muted small">
        {unlimited ? '可以重複播放' : playing ? '播放中…' : `剩 ${Math.max(0, left)} 次`}
      </span>
      {error && <span className="error small">{error}</span>}
    </div>
  )
}

export function Transcript({ passage }: { passage: Passage }) {
  const lines = passage.script ?? []
  if (!lines.length) return <PassageBody body={passage.body} />
  const showNames = passage.format === 'conversation'
  return (
    <div className="transcript">
      {lines.map((l, i) => (
        <p key={i}>{showNames && <strong>{l.speaker}：</strong>}{l.text}</p>
      ))}
    </div>
  )
}
