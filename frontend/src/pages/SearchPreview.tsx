import React, { useState } from 'react'
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

type SearchMode = 'hybrid' | 'vector' | 'fulltext'

interface PreviewData {
  entities: any[]
  sources: any[]
  relations: any[]
}

export default function SearchPreview() {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')
  const [mode, setMode] = useState<SearchMode>('hybrid')
  const [entityLimit, setEntityLimit] = useState('5')
  const [sourceLimit, setSourceLimit] = useState('5')
  const [relationLimit, setRelationLimit] = useState('5')
  const [previewData, setPreviewData] = useState<PreviewData | null>(null)
  const [loading, setLoading] = useState(false)

  const handlePreview = async (event: React.FormEvent) => {
    event.preventDefault()
    setLoading(true)
    try {
      const res = await fetch('/api/indexing/query-preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query,
          mode,
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
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">{t('search.page_title')}</h1>
      
      <Card>
        <CardHeader>
          <CardTitle>{t('search.query_configuration')}</CardTitle>
          <CardDescription>{t('search.rank_preview_desc')}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <form onSubmit={handlePreview} className="flex flex-col gap-4 max-w-2xl">
            <div className="grid gap-2">
              <Label>{t('search.query_label')}</Label>
              <Input value={query} onChange={(event) => setQuery(event.target.value)} required />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="grid gap-2">
                <Label>{t('search.search_mode')}</Label>
                <Select value={mode} onValueChange={(value) => setMode(value as SearchMode)}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="hybrid">{t('search.mode_hybrid')}</SelectItem>
                    <SelectItem value="vector">{t('search.mode_vector')}</SelectItem>
                    <SelectItem value="fulltext">{t('search.mode_fulltext')}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="grid grid-cols-3 gap-4">
              <div className="grid gap-2">
                <Label>{t('search.entity_limit')}</Label>
                <Input type="number" value={entityLimit} onChange={(event) => setEntityLimit(event.target.value)} />
              </div>
              <div className="grid gap-2">
                <Label>{t('search.source_limit')}</Label>
                <Input type="number" value={sourceLimit} onChange={(event) => setSourceLimit(event.target.value)} />
              </div>
              <div className="grid gap-2">
                <Label>{t('search.relation_limit')}</Label>
                <Input type="number" value={relationLimit} onChange={(event) => setRelationLimit(event.target.value)} />
              </div>
            </div>

            <Button type="submit" disabled={loading} className="w-fit">
              {loading ? t('search.searching') : t('search.submit')}
            </Button>
          </form>

          {previewData && (
            <div className="space-y-6 pt-6 mt-6 border-t">
              <div>
                <h3 className="mb-2 text-lg font-semibold">{t('search.entities')}</h3>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t('common.entity')}</TableHead>
                      <TableHead>{t('search.score_fulltext')}</TableHead>
                      <TableHead>{t('search.score_vector')}</TableHead>
                      <TableHead>{t('search.score_hybrid')}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {previewData.entities.map((entity, index) => (
                      <TableRow key={index}>
                        <TableCell>{entity.name || entity.entity_id}</TableCell>
                        <TableCell>{entity.fulltext_score?.toFixed?.(4) ?? 'N/A'}</TableCell>
                        <TableCell>{entity.vector_score?.toFixed?.(4) ?? 'N/A'}</TableCell>
                        <TableCell>{entity.hybrid_score?.toFixed?.(4) ?? 'N/A'}</TableCell>
                      </TableRow>
                    ))}
                    {previewData.entities.length === 0 && (
                      <TableRow>
                        <TableCell colSpan={4} className="text-center text-muted-foreground">{t('common.no_results')}</TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </div>

              <div>
                <h3 className="mb-2 text-lg font-semibold">{t('search.sources')}</h3>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t('common.title')}</TableHead>
                      <TableHead>{t('search.score_fulltext')}</TableHead>
                      <TableHead>{t('search.score_vector')}</TableHead>
                      <TableHead>{t('search.score_hybrid')}</TableHead>
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
                    {previewData.sources.length === 0 && (
                      <TableRow>
                        <TableCell colSpan={4} className="text-center text-muted-foreground">{t('common.no_results')}</TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </div>

              <div>
                <h3 className="mb-2 text-lg font-semibold">{t('search.relations')}</h3>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t('search.left_entity')}</TableHead>
                      <TableHead>{t('search.right_entity')}</TableHead>
                      <TableHead>{t('search.score_fulltext')}</TableHead>
                      <TableHead>{t('search.score_vector')}</TableHead>
                      <TableHead>{t('search.score_hybrid')}</TableHead>
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
                    {previewData.relations.length === 0 && (
                      <TableRow>
                        <TableCell colSpan={5} className="text-center text-muted-foreground">{t('common.no_results')}</TableCell>
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
