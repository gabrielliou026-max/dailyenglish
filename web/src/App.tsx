import { useEffect, useState } from 'react'
import type { Session } from '@supabase/supabase-js'
import { configured, loadSkillLabels, supabase } from './lib/supabase'
import Login from './pages/Login'
import Home from './pages/Home'
import Quiz from './pages/Quiz'
import Stats from './pages/Stats'

export type View = { name: 'home' } | { name: 'quiz'; setId: string } | { name: 'stats' }

export default function App() {
  const [session, setSession] = useState<Session | null | undefined>(undefined)
  const [view, setView] = useState<View>({ name: 'home' })
  const [labels, setLabels] = useState<Record<string, string>>({})

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => setSession(data.session))
    const { data } = supabase.auth.onAuthStateChange((_e, s) => setSession(s))
    return () => data.subscription.unsubscribe()
  }, [])

  useEffect(() => {
    if (session) loadSkillLabels().then(setLabels).catch(() => {})
  }, [session])

  if (!configured) {
    return (
      <main className="page">
        <h1>尚未設定</h1>
        <p>請設定 VITE_SUPABASE_URL 與 VITE_SUPABASE_ANON_KEY 環境變數後重新部署。</p>
      </main>
    )
  }
  if (session === undefined) return <main className="page center">載入中…</main>
  if (!session) return <Login />

  switch (view.name) {
    case 'quiz':
      return <Quiz setId={view.setId} labels={labels} go={setView} />
    case 'stats':
      return <Stats labels={labels} go={setView} />
    default:
      return <Home go={setView} />
  }
}
