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

  useEffect(() => {
    fetch('/api/jobs')
      .then(res => res.json())
      .then(data => setJobs(data))
      .catch(console.error)
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

  return (
    <div className="grid gap-8">
      <Card>
        <CardHeader>
          <CardTitle>{t('Create Task')}</CardTitle>
          <CardDescription>Submit a new knowledge graph construction task.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="grid gap-6">
            <div className="grid gap-2">
              <Label>{t('Task Type')}</Label>
              <Select value={inputType} onValueChange={(val) => setInputType(val || 'url')}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="url">URL</SelectItem>
                  <SelectItem value="instruction">{t('Instruction')}</SelectItem>
                  <SelectItem value="entity">{t('Entity Name')}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {inputType === 'url' && (
              <div className="grid gap-2">
                <Label>{t('URL')}</Label>
                <Input value={url} onChange={e => setUrl(e.target.value)} placeholder={t('URL Placeholder')} type="url" required />
              </div>
            )}

            {inputType === 'instruction' && (
              <div className="grid gap-2">
                <Label>{t('Instruction')}</Label>
                <Textarea value={instruction} onChange={e => setInstruction(e.target.value)} placeholder={t('Instruction Placeholder')} required rows={4} />
              </div>
            )}

            {inputType === 'entity' && (
              <div className="grid gap-2">
                <Label>{t('Entity Name')}</Label>
                <Input value={entityName} onChange={e => setEntityName(e.target.value)} placeholder={t('Entity Placeholder')} required />
              </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div className="grid gap-2">
                <Label>{t('Max Depth')}</Label>
                <Input value={maxDepth} onChange={e => setMaxDepth(e.target.value)} type="number" min="0" />
              </div>
              <div className="grid gap-2">
                <Label>{t('Max Pages')}</Label>
                <Input value={maxPages} onChange={e => setMaxPages(e.target.value)} type="number" min="1" />
              </div>
              <div className="grid gap-2">
                <Label>{t('Concurrency')}</Label>
                <Input value={concurrency} onChange={e => setConcurrency(e.target.value)} type="number" min="1" />
              </div>
            </div>

            <div className="flex items-center space-x-2">
              <Checkbox id="filterUrls" checked={filterUrls} onCheckedChange={(checked) => setFilterUrls(checked as boolean)} />
              <Label htmlFor="filterUrls" className="cursor-pointer">{t('Filter URLs')}</Label>
            </div>

            <Button type="submit" className="w-full md:w-auto justify-self-start">{t('Submit')}</Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t('Task History')}</CardTitle>
        </CardHeader>
        <CardContent>
          {jobs.length > 0 ? (
            <div className="rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t('Job ID')}</TableHead>
                    <TableHead>{t('Type')}</TableHead>
                    <TableHead>{t('Seed')}</TableHead>
                    <TableHead>{t('Status')}</TableHead>
                    <TableHead className="text-right">{t('Visited')}</TableHead>
                    <TableHead className="text-right">{t('Failed')}</TableHead>
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
                        <Badge variant={job.status === 'completed' ? 'default' : job.status === 'failed' ? 'destructive' : 'secondary'}>
                          {job.status}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">{job.visited_count}</TableCell>
                      <TableCell className="text-right">{job.failed_count}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <p className="text-muted-foreground text-sm">{t('No tasks')}</p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
