import { useState, useEffect, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"

interface VectorIndexJob {
  job_id: string
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

export default function VectorIndexJobDetail() {
  const { jobId } = useParams<{ jobId: string }>()
  const { t } = useTranslation()
  const [job, setJob] = useState<VectorIndexJob | null>(null)
  const [events, setEvents] = useState<JobEvent[]>([])
  const eventsEndRef = useRef<HTMLDivElement>(null)

  const loadJob = async () => {
    try {
      const res = await fetch(`/api/vector-index/jobs/${jobId}`)
      if (res.ok) {
        setJob(await res.json())
      }
    } catch (err) {
      console.error(err)
    }
  }

  const loadEvents = async () => {
    try {
      const res = await fetch(`/api/vector-index/jobs/${jobId}/events`)
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

    const interval = setInterval(() => {
      loadJob()
      loadEvents()
    }, 2000)

    return () => clearInterval(interval)
  }, [jobId])

  useEffect(() => {
    if (job?.status === 'completed' || job?.status === 'failed') {
      // If terminal state, we could clear the interval, but it's okay, 
      // the effect cleanup handles unmount.
    }
  }, [job?.status])

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
            {t('Vector Index Job Detail')}
            <Badge variant={
              job.status === 'completed' ? 'default' :
              job.status === 'failed' ? 'destructive' : 'secondary'
            }>
              {job.status}
            </Badge>
          </h1>
          <p className="text-sm text-muted-foreground font-mono">
            {job.job_id}
          </p>
        </div>
        <div className="flex gap-2">
          <Link to="/vector-index">
            <Button variant="outline">{t('Vector Index Management')}</Button>
          </Link>
        </div>
      </div>

      <div className="grid gap-6 md:grid-cols-4 shrink-0">
        <Card>
          <CardHeader className="py-4">
            <CardTitle className="text-sm font-medium text-muted-foreground">{t('Mode')} / {t('Scope')}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{job.mode} / {job.scope}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="py-4">
            <CardTitle className="text-sm font-medium text-muted-foreground">{t('Scanned')}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{job.scanned_count}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="py-4">
            <CardTitle className="text-sm font-medium text-muted-foreground">{t('Synced')}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-green-600 dark:text-green-500">{job.synced_count}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="py-4">
            <CardTitle className="text-sm font-medium text-muted-foreground">{t('Failed')} / {t('Pending')}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-red-600 dark:text-red-500">{job.failed_count} / {job.pending_count}</div>
          </CardContent>
        </Card>
      </div>

      <Card className="flex-1 flex flex-col min-h-0">
        <CardHeader className="py-4 shrink-0">
          <CardTitle className="text-base">{t('Logs')}</CardTitle>
        </CardHeader>
        <CardContent className="flex-1 overflow-auto bg-muted/30 font-mono text-sm p-4 rounded-b-xl border-t">
          <div className="space-y-3">
            {events.map((ev) => (
              <div key={ev.event_id} className="flex gap-4">
                <span className="text-muted-foreground shrink-0">
                  {new Date(ev.created_at).toLocaleTimeString()}
                </span>
                <span className="text-blue-600 dark:text-blue-400 w-24 shrink-0">
                  [{ev.stage}]
                </span>
                <span className="flex-1">
                  {ev.message}
                  {Object.keys(ev.data).length > 0 && (
                    <span className="ml-2 text-muted-foreground">
                      {JSON.stringify(ev.data)}
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