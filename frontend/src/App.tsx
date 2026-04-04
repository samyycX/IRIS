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
import SearchApiAuth from './pages/SearchApiAuth'
import { Activity, Languages, LogOut } from 'lucide-react'
import { Button } from './components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './components/ui/card'
import { Input } from './components/ui/input'
import { Label } from './components/ui/label'
import { useAuth } from './lib/auth'


function isChineseLanguage(language: string) {
  return language.toLowerCase().startsWith('zh')
}

function LanguageSwitcher({ className = '' }: { className?: string }) {
  const { t, i18n } = useTranslation()
  const isChinese = isChineseLanguage(i18n.resolvedLanguage ?? i18n.language)
  const nextLanguageLabel = isChinese ? 'English' : '中文'

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      onClick={() => void i18n.changeLanguage(isChinese ? 'en' : 'zh')}
      className={`h-9 rounded-full border-border/70 bg-background/80 px-3 text-sm shadow-sm backdrop-blur supports-[backdrop-filter]:bg-background/70 ${className}`.trim()}
      aria-label={isChinese ? t('nav.switch_to_english') : t('nav.switch_to_chinese')}
      title={isChinese ? t('nav.switch_to_english') : t('nav.switch_to_chinese')}
    >
      <Languages className="h-4 w-4" />
      <span>{nextLanguageLabel}</span>
    </Button>
  )
}


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
    <div className="relative min-h-screen bg-background text-foreground grid place-items-center px-6">
      <div className="absolute right-6 top-6">
        <LanguageSwitcher />
      </div>
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
  const { t } = useTranslation()
  const { ready, authenticated, bypassEnabled, logout, loading } = useAuth()
  const location = useLocation()

  const getNavLinkClass = (path: string) => {
    return `text-sm transition-colors hover:text-foreground ${location.pathname === path ? 'font-semibold text-foreground' : 'text-muted-foreground'}`
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
      <header className="border-b px-6 py-4">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:gap-8">
            <Link to="/" className="flex items-center gap-2 font-semibold text-lg">
              <Activity className="w-5 h-5" />
              {t('app.brand')}
            </Link>
            <nav className="flex flex-wrap items-center gap-x-5 gap-y-2">
              <Link to="/" className={getNavLinkClass('/')}>{t('nav.home')}</Link>
              <Link to="/tasks" className={getNavLinkClass('/tasks')}>{t('nav.tasks') || 'Tasks'}</Link>
              <Link to="/search" className={getNavLinkClass('/search')}>{t('nav.search_preview')}</Link>
              <Link to="/indexing" className={getNavLinkClass('/indexing')}>{t('nav.index_management')}</Link>
              <Link to="/config" className={getNavLinkClass('/config')}>{t('nav.configuration')}</Link>
            </nav>
          </div>
          <div className="flex items-center justify-end gap-2">
            {!bypassEnabled ? (
              <Button type="button" variant="ghost" size="sm" onClick={() => void logout()} disabled={loading} className="h-9 gap-2 rounded-full px-3 text-sm">
                <LogOut className="h-4 w-4" />
                <span>{t('auth.logout')}</span>
              </Button>
            ) : null}
            <LanguageSwitcher />
          </div>
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
          <Route path="/config/search-api-auth" element={<SearchApiAuth />} />
        </Routes>
      </main>
    </div>
  )
}

export default App
