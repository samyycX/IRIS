import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
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

export default function VectorIndex() {
  const { t } = useTranslation()
  const navigate = useNavigate()

  // Job Creation state
  const [scope, setScope] = useState('all')
  const [batchSize, setBatchSize] = useState('16')

  // Preview state
  const [query, setQuery] = useState('')
  const [entityLimit, setEntityLimit] = useState('5')
  const [pageLimit, setPageLimit] = useState('5')
  const [relationLimit, setRelationLimit] = useState('5')
  const [previewData, setPreviewData] = useState<{entities: any[], pages: any[], relations: any[]} | null>(null)

  const handleStartJob = async (mode: 'backfill' | 'reindex') => {
    try {
      const res = await fetch(`/api/vector-index/${mode}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scope,
          batch_size: parseInt(batchSize, 10) || 16
        })
      })
      const data = await res.json()
      if (res.ok && data.job_id) {
        navigate(`/vector-index/jobs/${data.job_id}`)
      } else {
        alert(data.detail || 'Failed to start job')
      }
    } catch (err) {
      console.error(err)
      alert('Error starting job')
    }
  }

  const handlePreview = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!query) return
    try {
      const res = await fetch('/api/vector-index/query-preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query,
          entity_limit: parseInt(entityLimit, 10) || 5,
          page_limit: parseInt(pageLimit, 10) || 5,
          relation_limit: parseInt(relationLimit, 10) || 5
        })
      })
      const data = await res.json()
      if (res.ok) {
        setPreviewData(data)
      } else {
        alert(data.detail || 'Failed to fetch preview')
      }
    } catch (err) {
      console.error(err)
      alert('Error fetching preview')
    }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">{t('Vector Index Management')}</h1>

      <Card>
        <CardHeader>
          <CardTitle>{t('Create Task')}</CardTitle>
          <CardDescription>
            {t('Start a backfill or reindex task to generate embeddings for nodes.')}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-4 max-w-md">
            <div className="grid gap-2">
              <Label>{t('Scope')}</Label>
              <Select value={scope} onValueChange={(val) => setScope(val || 'all')}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">{t('All')}</SelectItem>
                  <SelectItem value="entity">{t('Entity')}</SelectItem>
                  <SelectItem value="page">{t('Page')}</SelectItem>
                  <SelectItem value="relation">{t('Relation')}</SelectItem>
                </SelectContent>
              </Select>
            </div>
            
            <div className="grid gap-2">
              <Label>{t('Batch Size')}</Label>
              <Input 
                type="number" 
                value={batchSize} 
                onChange={e => setBatchSize(e.target.value)} 
                min="1" 
              />
            </div>

            <div className="flex gap-4 mt-2">
              <Button onClick={() => handleStartJob('backfill')}>
                {t('Backfill')}
              </Button>
              <Button variant="destructive" onClick={() => handleStartJob('reindex')}>
                {t('Reindex')}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t('Query Preview')}</CardTitle>
          <CardDescription>
            {t('Test the hybrid vector search.')}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handlePreview} className="flex flex-col gap-4 max-w-md">
            <div className="grid gap-2">
              <Label>{t('Query')}</Label>
              <Input 
                value={query} 
                onChange={e => setQuery(e.target.value)} 
                placeholder={t('Search')} 
                required 
              />
            </div>
            
            <div className="grid grid-cols-3 gap-4">
              <div className="grid gap-2">
                <Label>{t('Entity Limit')}</Label>
                <Input 
                  type="number" 
                  value={entityLimit} 
                  onChange={e => setEntityLimit(e.target.value)} 
                  min="1" 
                  max="20" 
                />
              </div>
              <div className="grid gap-2">
                <Label>{t('Relation Limit')}</Label>
                <Input 
                  type="number" 
                  value={relationLimit} 
                  onChange={e => setRelationLimit(e.target.value)} 
                  min="1" 
                  max="20" 
                />
              </div>
              <div className="grid gap-2">
                <Label>{t('Page Limit')}</Label>
                <Input 
                  type="number" 
                  value={pageLimit} 
                  onChange={e => setPageLimit(e.target.value)} 
                  min="1" 
                  max="20" 
                />
              </div>
            </div>

            <Button type="submit">{t('Search')}</Button>
          </form>

          {previewData && (
            <div className="mt-8 space-y-6">
              <div>
                <h3 className="text-lg font-semibold mb-2">{t('Entities')}</h3>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Entity</TableHead>
                      <TableHead>Category</TableHead>
                      <TableHead>Score (Hybrid)</TableHead>
                      <TableHead>Score (Vector)</TableHead>
                      <TableHead>Relations</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {previewData.entities.map((ent, idx) => (
                      <TableRow key={idx}>
                        <TableCell className="font-medium">{ent.name}</TableCell>
                        <TableCell>{ent.category}</TableCell>
                        <TableCell>{ent.hybrid_score?.toFixed(4) || 'N/A'}</TableCell>
                        <TableCell>{ent.vector_score?.toFixed(4) || 'N/A'}</TableCell>
                        <TableCell>{ent.relation_count}</TableCell>
                      </TableRow>
                    ))}
                    {previewData.entities.length === 0 && (
                      <TableRow>
                        <TableCell colSpan={5} className="text-center text-muted-foreground py-4">
                          No results
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </div>

              <div>
                <h3 className="text-lg font-semibold mb-2">{t('Pages')}</h3>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Title</TableHead>
                      <TableHead>URL</TableHead>
                      <TableHead>Score (Vector)</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {previewData.pages.map((p, idx) => (
                      <TableRow key={idx}>
                        <TableCell className="font-medium max-w-xs truncate" title={p.title || ''}>{p.title || 'Untitled'}</TableCell>
                        <TableCell className="max-w-xs truncate" title={p.source_key}>{p.source_key}</TableCell>
                        <TableCell>{p.score?.toFixed(4)}</TableCell>
                      </TableRow>
                    ))}
                    {previewData.pages.length === 0 && (
                      <TableRow>
                        <TableCell colSpan={3} className="text-center text-muted-foreground py-4">
                          No results
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </div>

              <div>
                <h3 className="text-lg font-semibold mb-2">{t('Relations')}</h3>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t('Left Entity')}</TableHead>
                      <TableHead>{t('Right Entity')}</TableHead>
                      <TableHead>{t('Score (Vector)')}</TableHead>
                      <TableHead>{t('Aggregated Relation Text')}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {previewData.relations.map((relation, idx) => (
                      <TableRow key={idx}>
                        <TableCell className="font-medium">{relation.left_entity_name || relation.left_entity_id || 'N/A'}</TableCell>
                        <TableCell>{relation.right_entity_name || relation.right_entity_id || 'N/A'}</TableCell>
                        <TableCell>{relation.score?.toFixed?.(4) ?? 'N/A'}</TableCell>
                        <TableCell className="max-w-xl truncate" title={relation.aggregated_text || ''}>
                          {relation.aggregated_text || relation.source_key}
                        </TableCell>
                      </TableRow>
                    ))}
                    {previewData.relations.length === 0 && (
                      <TableRow>
                        <TableCell colSpan={4} className="text-center text-muted-foreground py-4">
                          No results
                        </TableCell>
                      </TableRow>
                    )}
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