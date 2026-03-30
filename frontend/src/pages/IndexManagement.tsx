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
import { Input } from "@/components/ui/input"
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

type Scope = 'all' | 'entity' | 'source' | 'relation'
type IndexType = 'vector' | 'fulltext'
type Mode = 'backfill' | 'reindex'

interface IndexPlan {
  index_type: IndexType
  mode: Mode
  scope: Scope
  total_count: number
  counts: Record<string, number>
  candidates: Array<{
    source_type: string
    source_key: string
    title?: string | null
    name?: string | null
    summary?: string | null
    aggregated_text?: string | null
    left_entity_name?: string | null
    right_entity_name?: string | null
  }>
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

interface PreviewData {
  entities: any[]
  sources: any[]
  relations: any[]
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
  const [batchSize, setBatchSize] = useState('16')
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
      const res = await fetch('/api/indexing/prepare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          index_type: indexType,
          mode,
          scope,
          sample_limit: 8,
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
      const res = await fetch(`/api/indexing/${planMode}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          index_type: indexType,
          scope,
          batch_size: parseInt(batchSize, 10) || 16,
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
      const res = await fetch('/api/indexing/fulltext/build', { method: 'POST' })
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
      const res = await fetch(`/api/indexing/fulltext/rebuild/${scope}`, { method: 'POST' })
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
          <Label>{t('Scope')}</Label>
          <Select value={scope} onValueChange={(value) => setScope((value || 'all') as Scope)}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t('All')}</SelectItem>
              <SelectItem value="entity">{t('Entity')}</SelectItem>
              <SelectItem value="source">{t('Source')}</SelectItem>
              <SelectItem value="relation">{t('Relation')}</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {indexType === 'fulltext' && (
          <div className="space-y-3 rounded-lg border p-4">
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm font-medium">{t('Fulltext Index Status')}</div>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={onRefreshStatuses} disabled={loading}>
                  {t('Check')}
                </Button>
                <Button variant="outline" size="sm" onClick={handleEnsureFulltext} disabled={loading}>
                  {t('Build')}
                </Button>
                <Button variant="destructive" size="sm" onClick={handleRebuildFulltext} disabled={loading}>
                  {t('Rebuild')}
                </Button>
              </div>
            </div>
            <div className="space-y-2">
              {relevantStatuses.map((status) => (
                <div key={status.name} className="flex items-center justify-between text-sm">
                  <span>{status.scope}</span>
                  <span className="flex items-center gap-2">
                    <Badge variant={status.exists ? 'default' : 'secondary'}>
                      {status.exists ? status.state || 'online' : t('Missing')}
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
                <div className="text-sm text-muted-foreground">{t('No status data')}</div>
              )}
            </div>
          </div>
        )}

        <div className="flex gap-3">
          <Button onClick={() => handlePrepare('backfill')} disabled={loading}>
            {t('Prepare Backfill')}
          </Button>
          <Button variant="destructive" onClick={() => handlePrepare('reindex')} disabled={loading}>
            {t('Prepare Reindex')}
          </Button>
        </div>

        {plan && (
          <div className="space-y-4 rounded-lg border p-4">
            <div className="space-y-1">
              <div className="text-sm font-medium">
                {t('Prepared Candidates')}: {plan.total_count}
              </div>
              <div className="text-sm text-muted-foreground">
                entity={plan.counts.entity || 0}, source={plan.counts.source || 0}, relation={plan.counts.relation || 0}
              </div>
            </div>

            <div className="grid gap-2">
              <Label>{t('Batch Size')}</Label>
              <Input
                type="number"
                value={batchSize}
                min="1"
                onChange={(event) => setBatchSize(event.target.value)}
              />
            </div>

            <div className="space-y-2">
              <div className="text-sm font-medium">{t('Candidate Samples')}</div>
              <div className="space-y-2">
                {plan.candidates.map((candidate) => (
                  <div key={`${candidate.source_type}-${candidate.source_key}`} className="rounded border p-2 text-sm">
                    <div className="font-medium">
                      {candidate.name || candidate.title || candidate.source_key}
                    </div>
                    <div className="text-muted-foreground">
                      {candidate.left_entity_name && candidate.right_entity_name
                        ? `${candidate.left_entity_name} -> ${candidate.right_entity_name}`
                        : candidate.source_key}
                    </div>
                  </div>
                ))}
                {plan.candidates.length === 0 && (
                  <div className="text-sm text-muted-foreground">{t('No candidates')}</div>
                )}
              </div>
            </div>

            <Button onClick={handleRun} disabled={loading || plan.total_count === 0}>
              {t('Confirm And Run')}
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
  const [query, setQuery] = useState('')
  const [entityLimit, setEntityLimit] = useState('5')
  const [sourceLimit, setSourceLimit] = useState('5')
  const [relationLimit, setRelationLimit] = useState('5')
  const [previewData, setPreviewData] = useState<PreviewData | null>(null)

  const loadJobs = async () => {
    try {
      const res = await fetch('/api/indexing/jobs')
      if (res.ok) {
        setJobs(await res.json())
      }
    } catch (err) {
      console.error(err)
    }
  }

  const loadStatuses = async () => {
    try {
      const res = await fetch('/api/indexing/status')
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

  const handlePreview = async (event: React.FormEvent) => {
    event.preventDefault()
    try {
      const res = await fetch('/api/indexing/query-preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query,
          entity_limit: parseInt(entityLimit, 10) || 5,
          source_limit: parseInt(sourceLimit, 10) || 5,
          relation_limit: parseInt(relationLimit, 10) || 5,
        }),
      })
      const data = await res.json()
      if (res.ok) {
        setPreviewData(data)
      } else {
        alert(data.detail || 'Failed to fetch preview')
      }
    } catch (err) {
      console.error(err)
      alert('Failed to fetch preview')
    }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">{t('Index Management')}</h1>

      <div className="grid gap-6 lg:grid-cols-2">
        <IndexOperationCard
          indexType="vector"
          title={t('Vector Index')}
          description={t('Prepare and run embedding indexing jobs.')}
          onJobCreated={loadJobs}
          fulltextStatuses={statuses}
          onRefreshStatuses={loadStatuses}
        />
        <IndexOperationCard
          indexType="fulltext"
          title={t('Fulltext Index')}
          description={t('Build, check, rebuild, and backfill searchable fulltext documents.')}
          onJobCreated={loadJobs}
          fulltextStatuses={statuses}
          onRefreshStatuses={loadStatuses}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{t('Recent Index Jobs')}</CardTitle>
          <CardDescription>{t('Jobs are kept in backend memory and disappear after service restart.')}</CardDescription>
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
                  {t('View Progress')}
                </Link>
              </div>
            </div>
          ))}
          {jobs.length === 0 && <div className="text-sm text-muted-foreground">{t('No jobs')}</div>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t('Query Preview')}</CardTitle>
          <CardDescription>{t('Preview fulltext, vector, and hybrid scores together.')}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <form onSubmit={handlePreview} className="flex flex-col gap-4 max-w-md">
            <div className="grid gap-2">
              <Label>{t('Query')}</Label>
              <Input value={query} onChange={(event) => setQuery(event.target.value)} required />
            </div>
            <div className="grid grid-cols-3 gap-4">
              <div className="grid gap-2">
                <Label>{t('Entity Limit')}</Label>
                <Input type="number" value={entityLimit} onChange={(event) => setEntityLimit(event.target.value)} />
              </div>
              <div className="grid gap-2">
                <Label>{t('Source Limit')}</Label>
                <Input type="number" value={sourceLimit} onChange={(event) => setSourceLimit(event.target.value)} />
              </div>
              <div className="grid gap-2">
                <Label>{t('Relation Limit')}</Label>
                <Input type="number" value={relationLimit} onChange={(event) => setRelationLimit(event.target.value)} />
              </div>
            </div>
            <Button type="submit">{t('Search')}</Button>
          </form>

          {previewData && (
            <div className="space-y-6">
              <div>
                <h3 className="mb-2 text-lg font-semibold">{t('Entities')}</h3>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t('Entity')}</TableHead>
                      <TableHead>{t('Fulltext Score')}</TableHead>
                      <TableHead>{t('Vector Score')}</TableHead>
                      <TableHead>{t('Hybrid Score')}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {previewData.entities.map((entity, index) => (
                      <TableRow key={index}>
                        <TableCell>{entity.name}</TableCell>
                        <TableCell>{entity.fulltext_score?.toFixed?.(4) ?? 'N/A'}</TableCell>
                        <TableCell>{entity.vector_score?.toFixed?.(4) ?? 'N/A'}</TableCell>
                        <TableCell>{entity.hybrid_score?.toFixed?.(4) ?? 'N/A'}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              <div>
                <h3 className="mb-2 text-lg font-semibold">{t('Sources')}</h3>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t('Title')}</TableHead>
                      <TableHead>{t('Fulltext Score')}</TableHead>
                      <TableHead>{t('Vector Score')}</TableHead>
                      <TableHead>{t('Hybrid Score')}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {previewData.sources.map((source, index) => (
                      <TableRow key={index}>
                        <TableCell>{source.title || source.source_key}</TableCell>
                        <TableCell>{source.fulltext_score?.toFixed?.(4) ?? 'N/A'}</TableCell>
                        <TableCell>{source.vector_score?.toFixed?.(4) ?? 'N/A'}</TableCell>
                        <TableCell>{source.hybrid_score?.toFixed?.(4) ?? 'N/A'}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              <div>
                <h3 className="mb-2 text-lg font-semibold">{t('Relations')}</h3>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t('Left Entity')}</TableHead>
                      <TableHead>{t('Right Entity')}</TableHead>
                      <TableHead>{t('Fulltext Score')}</TableHead>
                      <TableHead>{t('Vector Score')}</TableHead>
                      <TableHead>{t('Hybrid Score')}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {previewData.relations.map((relation, index) => (
                      <TableRow key={index}>
                        <TableCell>{relation.left_entity_name || relation.left_entity_id}</TableCell>
                        <TableCell>{relation.right_entity_name || relation.right_entity_id}</TableCell>
                        <TableCell>{relation.fulltext_score?.toFixed?.(4) ?? 'N/A'}</TableCell>
                        <TableCell>{relation.vector_score?.toFixed?.(4) ?? 'N/A'}</TableCell>
                        <TableCell>{relation.hybrid_score?.toFixed?.(4) ?? 'N/A'}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
