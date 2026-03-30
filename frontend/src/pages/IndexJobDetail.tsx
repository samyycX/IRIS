import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"

interface IndexJob {
  job_id: string
  index_type: string
  mode: string
  scope: string
  status: string
  created_at: string
  updated_at: string
  completed_at: string | null
  batch_size: number
  scanned_count: number
  synced_count: number
  failed_count: number
  pending_count: number
  last_error: string | null
}

interface JobEvent {
  event_id: string
  stage: string
  message: string
  created_at: string
  data: any
}

export default function IndexJobDetail() {
  const { jobId } = useParams<{ jobId: string }>()
  const { t } = useTranslation()
  const [job, setJob] = useState<IndexJob | null>(null)
  const [events, setEvents] = useState<JobEvent[]>([])
  const eventsEndRef = useRef<HTMLDivElement>(null)

  const loadJob = async () => {
    try {
      const res = await fetch(`/api/indexing/jobs/${jobId}`)
      if (res.ok) {
        setJob(await res.json())
      }
    } catch (err) {
      console.error(err)
    }
  }

  const loadEvents = async () => {
    try {
      const res = await fetch(`/api/indexing/jobs/${jobId}/events`)
      if (res.ok) {
        setEvents(await res.json())
      }
    } catch (err) {
      console.error(err)
    }
  }

  useEffect(() => {
    loadJob()
    loadEvents()
    const timer = setInterval(() => {
      loadJob()
      loadEvents()
    }, 2000)
    return () => clearInterval(timer)
  }, [jobId])

  useEffect(() => {
    eventsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [events])

  if (!job) {
    return <div className="p-8 text-center text-muted-foreground">Loading...</div>
  }

  return (
    <div className="space-y-6 flex flex-col h-[calc(100vh-8rem)]">
      <div className="flex items-center justify-between shrink-0">
        <div className="space-y-1">
          <h1 className="text-2xl font-bold flex items-center gap-3">
            {t('index.job_detail')}
            <Badge variant={job.status === 'failed' ? 'destructive' : job.status === 'completed' ? 'default' : 'secondary'}>
              {job.status}
            </Badge>
          </h1>
          <div className="text-sm text-muted-foreground">
            {job.index_type} / {job.mode} / {job.scope}
          </div>
          <p className="text-sm text-muted-foreground font-mono">{job.job_id}</p>
        </div>
        <Link to="/indexing">
          <Button variant="outline">{t('index.management')}</Button>
        </Link>
      </div>

      <div className="grid gap-6 md:grid-cols-4 shrink-0">
        <Card>
          <CardHeader className="py-4">
            <CardTitle className="text-sm font-medium text-muted-foreground">{t('index.index_type')}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{job.index_type}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="py-4">
            <CardTitle className="text-sm font-medium text-muted-foreground">{t('index.scanned')}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{job.scanned_count}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="py-4">
            <CardTitle className="text-sm font-medium text-muted-foreground">{t('index.synced')}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-green-600 dark:text-green-500">{job.synced_count}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="py-4">
            <CardTitle className="text-sm font-medium text-muted-foreground">{t('job.failed')} / {t('index.pending')}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-red-600 dark:text-red-500">{job.failed_count} / {job.pending_count}</div>
          </CardContent>
        </Card>
      </div>

      <Card className="flex-1 flex flex-col min-h-0">
        <CardHeader className="py-4 shrink-0">
          <CardTitle className="text-base">{t('job.logs')}</CardTitle>
        </CardHeader>
        <CardContent className="flex-1 overflow-auto bg-muted/30 font-mono text-sm p-4 rounded-b-xl border-t">
          <div className="space-y-3">
            {events.map((event) => (
              <div key={event.event_id} className="flex gap-4">
                <span className="text-muted-foreground shrink-0">
                  {new Date(event.created_at).toLocaleTimeString()}
                </span>
                <span className="text-blue-600 dark:text-blue-400 w-24 shrink-0">
                  [{event.stage}]
                </span>
                <span className="flex-1">
                  {event.message}
                  {Object.keys(event.data || {}).length > 0 && (
                    <span className="ml-2 text-muted-foreground">
                      {JSON.stringify(event.data)}
                    </span>
                  )}
                </span>
              </div>
            ))}
            <div ref={eventsEndRef} />
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
