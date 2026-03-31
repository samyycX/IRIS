import { Routes, Route, Link, useLocation } from 'react-router-dom'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import Home from './pages/Home'
import Tasks from './pages/Tasks'
import JobDetail from './pages/JobDetail'
import IndexManagement from './pages/IndexManagement'
import IndexJobDetail from './pages/IndexJobDetail'
import SearchPreview from './pages/SearchPreview'
import Configuration from './pages/Configuration'
import { Activity } from 'lucide-react'
import { Button } from './components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './components/ui/card'
import { Input } from './components/ui/input'
import { Label } from './components/ui/label'
import { useAuth } from './lib/auth'


function LoginScreen() {
  const { t } = useTranslation()
  const { login, loading } = useAuth()
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setError('')
    const result = await login(password)
    if (!result.ok) {
      setError(t(result.error))
      return
    }
    setPassword('')
  }

  return (
    <div className="min-h-screen bg-background text-foreground grid place-items-center px-6">
      <Card className="w-full max-w-md border-border/70 shadow-2xl shadow-black/10">
        <CardHeader className="space-y-3">
          <div className="flex items-center gap-3 text-lg font-semibold">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary/10 text-primary">
              <Activity className="h-5 w-5" />
            </div>
            {t('auth.title')}
          </div>
          <CardTitle>{t('auth.subtitle')}</CardTitle>
          <CardDescription>{t('auth.description')}</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="grid gap-4" onSubmit={handleSubmit}>
            <div className="grid gap-2">
              <Label htmlFor="iris-password">{t('auth.password_label')}</Label>
              <Input
                id="iris-password"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder={t('auth.password_placeholder')}
                autoComplete="current-password"
                required
              />
            </div>
            {error ? <div className="text-sm text-destructive">{error}</div> : null}
            <Button type="submit" disabled={loading}>
              {loading ? t('auth.submitting') : t('auth.submit')}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}

function App() {
  const { t, i18n } = useTranslation()
  const { ready, authenticated, bypassEnabled, logout, loading } = useAuth()
  const location = useLocation()

  const toggleLanguage = () => {
    i18n.changeLanguage(i18n.language === 'zh' ? 'en' : 'zh')
  }

  const getNavLinkClass = (path: string) => {
    return `text-sm hover:underline ${location.pathname === path ? 'font-bold' : ''}`
  }

  if (!ready) {
    return (
      <div className="min-h-screen bg-background text-foreground grid place-items-center px-6">
        <div className="text-sm text-muted-foreground">{t('auth.loading')}</div>
      </div>
    )
  }

  if (!authenticated && !bypassEnabled) {
    return <LoginScreen />
  }

  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col font-sans">
      <header className="border-b px-6 py-4 flex items-center justify-between">
        <Link to="/" className="flex items-center gap-2 font-semibold text-lg">
          <Activity className="w-5 h-5" />
          {t('app.brand')}
        </Link>
        <div className="flex gap-4">
          <Link to="/" className={getNavLinkClass('/')}>{t('nav.home')}</Link>
          <Link to="/tasks" className={getNavLinkClass('/tasks')}>{t('nav.tasks') || 'Tasks'}</Link>
          <Link to="/search" className={getNavLinkClass('/search')}>{t('nav.search_preview')}</Link>
          <Link to="/indexing" className={getNavLinkClass('/indexing')}>{t('nav.index_management')}</Link>
          <Link to="/config" className={getNavLinkClass('/config')}>{t('nav.configuration')}</Link>
          {!bypassEnabled ? (
            <button onClick={() => void logout()} className="text-sm hover:underline" disabled={loading}>
              {t('auth.logout')}
            </button>
          ) : null}
          <button onClick={toggleLanguage} className="text-sm hover:underline">
            {i18n.language === 'zh' ? 'English' : '中文'}
          </button>
        </div>
      </header>
      <main className="flex-1 p-6 max-w-6xl mx-auto w-full">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/tasks" element={<Tasks />} />
          <Route path="/jobs/:jobId" element={<JobDetail />} />
          <Route path="/indexing" element={<IndexManagement />} />
          <Route path="/indexing/jobs/:jobId" element={<IndexJobDetail />} />
          <Route path="/search" element={<SearchPreview />} />
          <Route path="/config" element={<Configuration />} />
        </Routes>
      </main>
    </div>
  )
}

export default App
