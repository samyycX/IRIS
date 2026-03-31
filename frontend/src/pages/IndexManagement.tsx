import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { apiFetch } from '@/lib/auth'

type Scope = 'all' | 'entity' | 'source' | 'relation'
type IndexType = 'vector' | 'fulltext'
type Mode = 'backfill' | 'reindex'

interface IndexPlan {
  index_type: IndexType
  mode: Mode
  scope: Scope
  total_count: number
  counts: Record<string, number>
}

interface IndexJobSummary {
  job_id: string
  index_type: IndexType
  mode: string
  scope: string
  status: string
  updated_at: string
}

interface IndexStatusEntry {
  index_type: IndexType
  scope: Scope
  name: string
  exists: boolean
  state?: string | null
  population_percent?: number | null
}

function IndexOperationCard({
  indexType,
  title,
  description,
  onJobCreated,
  fulltextStatuses,
  onRefreshStatuses,
}: {
  indexType: IndexType
  title: string
  description: string
  onJobCreated: () => void
  fulltextStatuses: IndexStatusEntry[]
  onRefreshStatuses: () => Promise<void>
}) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [scope, setScope] = useState<Scope>('all')
  const [plan, setPlan] = useState<IndexPlan | null>(null)
  const [planMode, setPlanMode] = useState<Mode>('backfill')
  const [loading, setLoading] = useState(false)

  const relevantStatuses = useMemo(
    () => fulltextStatuses.filter((item) => item.index_type === 'fulltext'),
    [fulltextStatuses]
  )

  const handlePrepare = async (mode: Mode) => {
    setLoading(true)
    try {
      const res = await apiFetch('/api/indexing/prepare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          index_type: indexType,
          mode,
          scope,
          sample_limit: 0,
        }),
      })
      const data = await res.json()
      if (res.ok) {
        setPlan(data)
        setPlanMode(mode)
      } else {
        alert(data.detail || 'Failed to prepare indexing job')
      }
    } catch (err) {
      console.error(err)
      alert('Failed to prepare indexing job')
    } finally {
      setLoading(false)
    }
  }

  const handleRun = async () => {
    setLoading(true)
    try {
      const res = await apiFetch(`/api/indexing/${planMode}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          index_type: indexType,
          scope,
        }),
      })
      const data = await res.json()
      if (res.ok && data.job_id) {
        setPlan(null)
        onJobCreated()
        navigate(`/indexing/jobs/${data.job_id}`)
      } else {
        alert(data.detail || 'Failed to start indexing job')
      }
    } catch (err) {
      console.error(err)
      alert('Failed to start indexing job')
    } finally {
      setLoading(false)
    }
  }

  const handleEnsureFulltext = async () => {
    setLoading(true)
    try {
      const res = await apiFetch('/api/indexing/fulltext/build', { method: 'POST' })
      const data = await res.json()
      if (!res.ok) {
        alert(data.detail || 'Failed to build fulltext indexes')
      }
      await onRefreshStatuses()
    } catch (err) {
      console.error(err)
      alert('Failed to build fulltext indexes')
    } finally {
      setLoading(false)
    }
  }

  const handleRebuildFulltext = async () => {
    setLoading(true)
    try {
      const res = await apiFetch(`/api/indexing/fulltext/rebuild/${scope}`, { method: 'POST' })
      const data = await res.json()
      if (!res.ok) {
        alert(data.detail || 'Failed to rebuild fulltext indexes')
      }
      await onRefreshStatuses()
    } catch (err) {
      console.error(err)
      alert('Failed to rebuild fulltext indexes')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-2">
          <Label>{t('index.scope')}</Label>
          <Select value={scope} onValueChange={(value) => setScope((value || 'all') as Scope)}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t('common.all')}</SelectItem>
              <SelectItem value="entity">{t('common.entity')}</SelectItem>
              <SelectItem value="source">{t('common.source')}</SelectItem>
              <SelectItem value="relation">{t('common.relation')}</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {indexType === 'fulltext' && (
          <div className="space-y-3 rounded-lg border p-4">
            <div className="text-sm text-muted-foreground">
              {t('index.fulltext_property_note')}
            </div>
            <div className="flex items-center justify-between gap-3 pt-2">
              <div className="text-sm font-medium">{t('index.fulltext_status')}</div>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={onRefreshStatuses} disabled={loading}>
                  {t('index.check')}
                </Button>
                <Button variant="outline" size="sm" onClick={handleEnsureFulltext} disabled={loading}>
                  {t('index.build')}
                </Button>
                <Button variant="destructive" size="sm" onClick={handleRebuildFulltext} disabled={loading}>
                  {t('index.rebuild')}
                </Button>
              </div>
            </div>
            <div className="space-y-2">
              {relevantStatuses.map((status) => (
                <div key={status.name} className="flex items-center justify-between text-sm">
                  <span>{status.scope}</span>
                  <span className="flex items-center gap-2">
                    <Badge variant={status.exists ? 'default' : 'secondary'}>
                      {status.exists ? status.state || 'online' : t('index.missing')}
                    </Badge>
                    {status.population_percent != null && (
                      <span className="text-muted-foreground">
                        {status.population_percent.toFixed(0)}%
                      </span>
                    )}
                  </span>
                </div>
              ))}
              {relevantStatuses.length === 0 && (
                <div className="text-sm text-muted-foreground">{t('index.no_status_data')}</div>
              )}
            </div>
          </div>
        )}

        <div className="flex gap-3">
          <Button onClick={() => handlePrepare('backfill')} disabled={loading}>
            {t('index.prepare_backfill')}
          </Button>
          <Button variant="destructive" onClick={() => handlePrepare('reindex')} disabled={loading}>
            {t('index.prepare_reindex')}
          </Button>
        </div>

        {plan && (
          <div className="space-y-4 rounded-lg border p-4">
            <div className="space-y-1">
              <div className="text-sm font-medium">
                {t('index.prepared_candidates')}: {plan.total_count}
              </div>
              <div className="text-sm text-muted-foreground">
                entity={plan.counts.entity || 0}, source={plan.counts.source || 0}, relation={plan.counts.relation || 0}
              </div>
            </div>

            <Button onClick={handleRun} disabled={loading || plan.total_count === 0}>
              {t('index.confirm_and_run')}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export default function IndexManagement() {
  const { t } = useTranslation()
  const [jobs, setJobs] = useState<IndexJobSummary[]>([])
  const [statuses, setStatuses] = useState<IndexStatusEntry[]>([])

  const loadJobs = async () => {
    try {
      const res = await apiFetch('/api/indexing/jobs')
      if (res.ok) {
        setJobs(await res.json())
      }
    } catch (err) {
      console.error(err)
    }
  }

  const loadStatuses = async () => {
    try {
      const res = await apiFetch('/api/indexing/status')
      if (res.ok) {
        const data = await res.json()
        setStatuses(data.indexes || [])
      }
    } catch (err) {
      console.error(err)
    }
  }

  useEffect(() => {
    loadJobs()
    loadStatuses()
    const timer = setInterval(() => {
      loadJobs()
      loadStatuses()
    }, 3000)
    return () => clearInterval(timer)
  }, [])

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">{t('index.management')}</h1>

      <div className="grid gap-6 lg:grid-cols-2">
        <IndexOperationCard
          indexType="vector"
          title={t('index.vector')}
          description={t('index.vector_section_desc')}
          onJobCreated={loadJobs}
          fulltextStatuses={statuses}
          onRefreshStatuses={loadStatuses}
        />
        <IndexOperationCard
          indexType="fulltext"
          title={t('index.fulltext')}
          description={t('index.fulltext_section_desc')}
          onJobCreated={loadJobs}
          fulltextStatuses={statuses}
          onRefreshStatuses={loadStatuses}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{t('index.recent_jobs')}</CardTitle>
          <CardDescription>{t('index.jobs_volatile_note')}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {jobs.slice(0, 8).map((job) => (
            <div key={job.job_id} className="flex items-center justify-between rounded-lg border p-3 text-sm">
              <div className="space-y-1">
                <div className="font-medium">
                  {job.index_type} / {job.mode} / {job.scope}
                </div>
                <div className="text-muted-foreground">{job.job_id}</div>
              </div>
              <div className="flex items-center gap-3">
                <Badge variant={job.status === 'failed' ? 'destructive' : 'secondary'}>
                  {job.status}
                </Badge>
                <Link to={`/indexing/jobs/${job.job_id}`} className="text-blue-500 hover:underline">
                  {t('index.view_progress')}
                </Link>
              </div>
            </div>
          ))}
          {jobs.length === 0 && <div className="text-sm text-muted-foreground">{t('index.no_jobs')}</div>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t('index.query_preview')}</CardTitle>
          <CardDescription>
            {t('index.query_preview_moved')}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Link to="/search">
            <Button>{t('index.go_to_search_preview')}</Button>
          </Link>
        </CardContent>
      </Card>
    </div>
  )
}
