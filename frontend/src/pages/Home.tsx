import { useState, useEffect } from 'react'
import { useNavigate, Link } from 'react-router-dom'
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
import { Checkbox } from "@/components/ui/checkbox"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"

interface Job {
  job_id: string
  input_type: string
  seed: string
  status: string
  visited_count: number
  failed_count: number
  resume_available: boolean
}

export default function Home() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [jobs, setJobs] = useState<Job[]>([])
  
  const [inputType, setInputType] = useState('url')
  const [url, setUrl] = useState('')
  const [instruction, setInstruction] = useState('')
  const [entityName, setEntityName] = useState('')
  const [maxDepth, setMaxDepth] = useState('3')
  const [maxPages, setMaxPages] = useState('100')
  const [concurrency, setConcurrency] = useState('5')
  const [filterUrls, setFilterUrls] = useState(true)

  const loadJobs = async () => {
    try {
      const res = await fetch('/api/jobs')
      const data = await res.json()
      if (Array.isArray(data)) {
        setJobs(data)
      }
    } catch (err) {
      console.error(err)
    }
  }

  useEffect(() => {
    loadJobs()
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const payload = {
      input_type: inputType,
      url: url || null,
      instruction: instruction || null,
      entity_name: entityName || null,
      max_depth: maxDepth ? parseInt(maxDepth) : null,
      max_pages: maxPages ? parseInt(maxPages) : null,
      crawl_concurrency: concurrency ? parseInt(concurrency) : null,
      filter_candidate_urls: filterUrls
    }

    try {
      const res = await fetch('/api/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
      const data = await res.json()
      if (data.job_id) {
        navigate(`/jobs/${data.job_id}`)
      }
    } catch (err) {
      console.error(err)
    }
  }

  const handleResume = async (jobId: string) => {
    try {
      const res = await fetch(`/api/jobs/${jobId}/resume`, {
        method: 'POST',
      })
      if (!res.ok) {
        throw new Error(`Resume failed: ${res.status}`)
      }
      await loadJobs()
      navigate(`/jobs/${jobId}`)
    } catch (err) {
      console.error(err)
    }
  }

  const handlePause = async (jobId: string) => {
    try {
      const res = await fetch(`/api/jobs/${jobId}/pause`, {
        method: 'POST',
      })
      if (!res.ok) {
        throw new Error(`Pause failed: ${res.status}`)
      }
      await loadJobs()
      navigate(`/jobs/${jobId}`)
    } catch (err) {
      console.error(err)
    }
  }

  const handleCancel = async (jobId: string) => {
    try {
      const res = await fetch(`/api/jobs/${jobId}/cancel`, {
        method: 'POST',
      })
      if (!res.ok) {
        throw new Error(`Cancel failed: ${res.status}`)
      }
      await loadJobs()
      navigate(`/jobs/${jobId}`)
    } catch (err) {
      console.error(err)
    }
  }

  const getStatusVariant = (status: string) => {
    if (status === 'completed') return 'default'
    if (status === 'failed') return 'destructive'
    if (status === 'cancelled') return 'destructive'
    if (status === 'paused') return 'outline'
    if (status === 'interrupted') return 'outline'
    return 'secondary'
  }

  return (
    <div className="grid gap-8">
      <Card>
        <CardHeader>
          <CardTitle>{t('crawl.create_task')}</CardTitle>
          <CardDescription>Submit a new knowledge graph construction task.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="grid gap-6">
            <div className="grid gap-2">
              <Label>{t('crawl.task_type')}</Label>
              <Select value={inputType} onValueChange={(val) => setInputType(val || 'url')}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="url">URL</SelectItem>
                  <SelectItem value="instruction">{t('crawl.instruction')}</SelectItem>
                  <SelectItem value="entity">{t('crawl.entity_name')}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {inputType === 'url' && (
              <div className="grid gap-2">
                <Label>{t('crawl.url')}</Label>
                <Input value={url} onChange={e => setUrl(e.target.value)} placeholder={t('crawl.url_placeholder')} type="url" required />
              </div>
            )}

            {inputType === 'instruction' && (
              <div className="grid gap-2">
                <Label>{t('crawl.instruction')}</Label>
                <Textarea value={instruction} onChange={e => setInstruction(e.target.value)} placeholder={t('crawl.instruction_placeholder')} required rows={4} />
              </div>
            )}

            {inputType === 'entity' && (
              <div className="grid gap-2">
                <Label>{t('crawl.entity_name')}</Label>
                <Input value={entityName} onChange={e => setEntityName(e.target.value)} placeholder={t('crawl.entity_placeholder')} required />
              </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div className="grid gap-2">
                <Label>{t('crawl.max_depth')}</Label>
                <Input value={maxDepth} onChange={e => setMaxDepth(e.target.value)} type="number" min="0" />
              </div>
              <div className="grid gap-2">
                <Label>{t('crawl.max_pages')}</Label>
                <Input value={maxPages} onChange={e => setMaxPages(e.target.value)} type="number" min="1" />
              </div>
              <div className="grid gap-2">
                <Label>{t('crawl.concurrency')}</Label>
                <Input value={concurrency} onChange={e => setConcurrency(e.target.value)} type="number" min="1" />
              </div>
            </div>

            <div className="flex items-center space-x-2">
              <Checkbox id="filterUrls" checked={filterUrls} onCheckedChange={(checked) => setFilterUrls(checked as boolean)} />
              <Label htmlFor="filterUrls" className="cursor-pointer">{t('crawl.filter_urls')}</Label>
            </div>

            <Button type="submit" className="w-full md:w-auto justify-self-start">{t('crawl.submit')}</Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t('crawl.task_history')}</CardTitle>
        </CardHeader>
        <CardContent>
          {jobs.length > 0 ? (
            <div className="rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t('job.id')}</TableHead>
                    <TableHead>{t('job.type')}</TableHead>
                    <TableHead>{t('job.seed')}</TableHead>
                    <TableHead>{t('job.status')}</TableHead>
                    <TableHead className="text-right">{t('job.visited')}</TableHead>
                    <TableHead className="text-right">{t('job.failed')}</TableHead>
                    <TableHead className="text-right">{t('job.actions')}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {jobs.map(job => (
                    <TableRow key={job.job_id}>
                      <TableCell className="font-medium">
                        <Link to={`/jobs/${job.job_id}`} className="text-blue-500 hover:underline">
                          {job.job_id.slice(0, 8)}...
                        </Link>
                      </TableCell>
                      <TableCell>{job.input_type}</TableCell>
                      <TableCell className="max-w-[200px] truncate" title={job.seed}>{job.seed}</TableCell>
                      <TableCell>
                        <Badge variant={getStatusVariant(job.status)}>
                          {job.status}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">{job.visited_count}</TableCell>
                      <TableCell className="text-right">{job.failed_count}</TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-2">
                        {job.status === 'queued' || job.status === 'running' ? (
                          <Button variant="outline" size="sm" onClick={() => handlePause(job.job_id)}>
                            {t('job.pause')}
                          </Button>
                        ) : null}
                        {job.status !== 'completed' && job.status !== 'cancelled' ? (
                          <Button variant="destructive" size="sm" onClick={() => handleCancel(job.job_id)}>
                            {t('job.cancel')}
                          </Button>
                        ) : null}
                        {job.resume_available && (job.status === 'interrupted' || job.status === 'failed') ? (
                          <Button variant="outline" size="sm" onClick={() => handleResume(job.job_id)}>
                            {t('job.resume')}
                          </Button>
                        ) : null}
                        {job.resume_available && job.status === 'paused' ? (
                          <Button variant="outline" size="sm" onClick={() => handleResume(job.job_id)}>
                            {t('job.resume')}
                          </Button>
                        ) : null}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <p className="text-muted-foreground text-sm">{t('crawl.no_tasks')}</p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
