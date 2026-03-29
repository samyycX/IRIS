import { Routes, Route, Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import Home from './pages/Home'
import JobDetail from './pages/JobDetail'
import { Activity } from 'lucide-react'

function App() {
  const { t, i18n } = useTranslation()

  const toggleLanguage = () => {
    i18n.changeLanguage(i18n.language === 'zh' ? 'en' : 'zh')
  }

  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col font-sans">
      <header className="border-b px-6 py-4 flex items-center justify-between">
        <Link to="/" className="flex items-center gap-2 font-semibold text-lg">
          <Activity className="w-5 h-5" />
          {t('IRIS Project')}
        </Link>
        <div className="flex gap-4">
          <button onClick={toggleLanguage} className="text-sm hover:underline">
            {i18n.language === 'zh' ? 'English' : '中文'}
          </button>
        </div>
      </header>
      <main className="flex-1 p-6 max-w-6xl mx-auto w-full">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/jobs/:jobId" element={<JobDetail />} />
        </Routes>
      </main>
    </div>
  )
}

export default App
