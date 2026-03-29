import { useState, useEffect, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, Play, CheckCircle2, XCircle, Clock } from 'lucide-react'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"

interface JobEvent {
  created_at: string
  stage: string
  message: string
  data?: Record<string, any>
}

interface JobData {
  job_id: string
  status: string
  input_type: string
  seed: string
  visited_count: number
  failed_count: number
  start_time: string
  end_time?: string
}

export default function JobDetail() {
  const { jobId } = useParams<{ jobId: string }>()
  const { t } = useTranslation()
  const [job, setJob] = useState<JobData | null>(null)
  const [events, setEvents] = useState<JobEvent[]>([])
  const logsEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!jobId) return

    // Fetch initial job info
    fetch(`/api/jobs/${jobId}`)
      .then(res => res.json())
      .then(data => setJob(data))
      .catch(console.error)

    // Fetch existing events
    fetch(`/api/jobs/${jobId}/events`)
      .then(res => res.json())
      .then(data => {
        if (Array.isArray(data)) {
          setEvents(data)
        }
      })
      .catch(console.error)

    // Setup SSE
    const evtSource = new EventSource(`/api/jobs/${jobId}/stream`)
    
    evtSource.onmessage = (e) => {
      try {
        const evt = JSON.parse(e.data)
        setEvents(prev => [...prev, evt])
        
        setJob(prev => {
          if (!prev) return prev;
          let updated = { ...prev };
          if (evt.data?.job_status) updated.status = evt.data.job_status;
          if (evt.data?.visited_count !== undefined) updated.visited_count = evt.data.visited_count;
          if (evt.data?.failed_count !== undefined) updated.failed_count = evt.data.failed_count;
          return updated;
        })
      } catch (err) {
        console.error("Failed to parse SSE message", err)
      }
    }

    evtSource.onerror = () => {
      // Don't log error if it's just a normal close
      if (evtSource.readyState === EventSource.CLOSED) return
      evtSource.close()
    }

    return () => {
      evtSource.close()
    }
  }, [jobId])

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [events])

  if (!job) {
    return <div className="flex items-center justify-center h-64"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div></div>
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed': return <CheckCircle2 className="w-5 h-5 text-green-500" />
      case 'failed': return <XCircle className="w-5 h-5 text-red-500" />
      case 'running': return <Play className="w-5 h-5 text-blue-500" />
      default: return <Clock className="w-5 h-5 text-gray-500" />
    }
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed': return 'bg-green-500/10 text-green-500 hover:bg-green-500/20 border-green-500/20'
      case 'failed': return 'bg-red-500/10 text-red-500 hover:bg-red-500/20 border-red-500/20'
      case 'running': return 'bg-blue-500/10 text-blue-500 hover:bg-blue-500/20 border-blue-500/20'
      default: return 'bg-gray-500/10 text-gray-500 hover:bg-gray-500/20 border-gray-500/20'
    }
  }

  return (
    <div className="grid gap-6">
      <div className="flex items-center gap-4">
        <Link to="/">
          <Badge variant="outline" className="px-3 py-1 cursor-pointer hover:bg-secondary">
            <ArrowLeft className="w-4 h-4 mr-2" />
            {t('Back to Home')}
          </Badge>
        </Link>
        <h1 className="text-2xl font-bold">{t('Job Detail')}</h1>
      </div>

      <div className="grid gap-6 md:grid-cols-4">
        <Card className="md:col-span-1">
          <CardHeader>
            <CardTitle className="text-lg">Overview</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4">
            <div>
              <div className="text-sm font-medium text-muted-foreground">{t('Job ID')}</div>
              <div className="font-mono text-sm break-all">{job.job_id}</div>
            </div>
            <div>
              <div className="text-sm font-medium text-muted-foreground">{t('Status')}</div>
              <div className="flex items-center gap-2 mt-1">
                {getStatusIcon(job.status)}
                <Badge variant="outline" className={`capitalize ${getStatusColor(job.status)}`}>
                  {job.status}
                </Badge>
              </div>
            </div>
            <div>
              <div className="text-sm font-medium text-muted-foreground">{t('Type')}</div>
              <div className="uppercase">{job.input_type}</div>
            </div>
            <div>
              <div className="text-sm font-medium text-muted-foreground">{t('Seed')}</div>
              <div className="text-sm break-all">{job.seed}</div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <div className="text-sm font-medium text-muted-foreground">{t('Visited')}</div>
                <div className="text-2xl font-bold">{job.visited_count}</div>
              </div>
              <div>
                <div className="text-sm font-medium text-muted-foreground">{t('Failed')}</div>
                <div className="text-2xl font-bold">{job.failed_count}</div>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="md:col-span-3 flex flex-col min-h-[500px] max-h-[800px]">
          <CardHeader>
            <CardTitle>{t('Logs')}</CardTitle>
            <CardDescription>Live execution logs</CardDescription>
          </CardHeader>
          <CardContent className="flex-1 overflow-auto bg-black m-4 mt-0 rounded-md p-4 font-mono text-sm">
            <div className="space-y-2">
              {events.map((evt, idx) => (
                <div key={idx} className="flex gap-4">
                  <span className="text-gray-500 shrink-0">
                    {evt.created_at ? new Date(evt.created_at).toISOString().replace('T', ' ').substring(0, 23) : ''}
                  </span>
                  <span className={`shrink-0 w-24 ${
                    evt.stage === 'failed' ? 'text-red-400' :
                    evt.stage === 'queued' || evt.stage === 'completed' ? 'text-green-400' :
                    'text-blue-400'
                  }`}>
                    [{evt.stage.toUpperCase()}]
                  </span>
                  <span className="text-gray-200">
                    {evt.message}
                    {evt.data && Object.keys(evt.data).length > 0 && (
                      <pre className="mt-1 text-xs text-gray-500 overflow-x-auto">
                        {JSON.stringify(evt.data, null, 2)}
                      </pre>
                    )}
                  </span>
                </div>
              ))}
              <div ref={logsEndRef} />
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
