import { useState, useEffect } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { AlertTriangle, Server, Database, BrainCircuit, Component } from "lucide-react"
import { useTranslation } from "react-i18next"
import { apiFetch } from "@/lib/auth"

interface DependencyStatus {
  state: string
  configured: boolean
  available: boolean
  last_checked_at: string | null
  last_error: string | null
  details: {
    uri?: string
    base_url?: string
    model?: string
  }
}

interface StatusData {
  status: string
  checked_at: string
  neo4j: DependencyStatus
  llm: DependencyStatus
  embedding: DependencyStatus
  graph: {
    entity_count: number
    source_count: number
    relation_count: number
    stale: boolean
    last_updated_at: string | null
  }
}

export default function Home() {
  const { t } = useTranslation()
  const [status, setStatus] = useState<StatusData | null>(null)
  const [loading, setLoading] = useState(true)

  const loadStatus = async () => {
    try {
      const res = await apiFetch('/status')
      if (res.ok) {
        const data = await res.json()
        setStatus(data)
      }
    } catch (err) {
      console.error(t("home.load_status_failed"), err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadStatus()
  }, [])

  const getStatusDot = (dep: DependencyStatus) => {
    if (!dep.configured) {
      return <span className="w-3 h-3 rounded-full bg-gray-400" title={t("home.unconfigured")}></span>
    }
    if (dep.state === 'healthy' && dep.available) {
      return <span className="w-3 h-3 rounded-full bg-green-500" title={t("home.success")}></span>
    }
    return <span className="w-3 h-3 rounded-full bg-red-500" title={t("home.failed")}></span>
  }

  const renderModelName = (dep: DependencyStatus) => {
    if (!dep.configured) return <span className="text-muted-foreground">{t("home.unconfigured_short")}</span>
    
    const model = dep.details?.model || t("home.unknown_model");
    const isError = dep.state !== 'healthy' || !dep.available;
    
    return (
      <div className="flex items-center gap-2">
        <span className="font-mono text-sm">{model}</span>
        {isError && (
          <span title={t("home.unsuccessful_model")}>
            <AlertTriangle className="w-4 h-4 text-amber-500" />
          </span>
        )}
      </div>
    )
  }

  if (loading) {
    return <div className="p-8 text-center text-muted-foreground">{t("home.loading")}</div>
  }

  if (!status) {
    return <div className="p-8 text-center text-red-500">{t("home.load_failed")}</div>
  }

  return (
    <div className="grid gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{t("home.status_overview")}</h1>
          <p className="text-muted-foreground">{t("home.system_status_desc")}</p>
        </div>
      </div>

      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        {/* Component: Neo4j */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Database className="w-4 h-4 text-muted-foreground" />
              {t("home.neo4j_database")}
            </CardTitle>
            {getStatusDot(status.neo4j)}
          </CardHeader>
          <CardContent>
            <div className="text-xl font-bold mt-2 truncate max-w-full" title={status.neo4j.details?.uri}>
              {status.neo4j.configured ? (status.neo4j.details?.uri || t("home.uri_hidden")) : t("home.unconfigured_short")}
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              {status.neo4j.last_error ? (
                <span className="text-red-500">{status.neo4j.last_error}</span>
              ) : status.neo4j.state === 'healthy' ? t("home.connected_success") : t("home.unavailable")}
            </p>
          </CardContent>
        </Card>

        {/* Component: LLM */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <BrainCircuit className="w-4 h-4 text-muted-foreground" />
              {t("home.llm_engine")}
            </CardTitle>
            {getStatusDot(status.llm)}
          </CardHeader>
          <CardContent>
            <div className="mt-2 text-xl font-bold">
              {renderModelName(status.llm)}
            </div>
            <p className="text-xs text-muted-foreground mt-1" title={status.llm.details?.base_url}>
              {status.llm.configured ? status.llm.details?.base_url : t("home.please_configure")}
            </p>
          </CardContent>
        </Card>

        {/* Component: Embedding */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Component className="w-4 h-4 text-muted-foreground" />
              {t("home.embedding_model")}
            </CardTitle>
            {getStatusDot(status.embedding)}
          </CardHeader>
          <CardContent>
            <div className="mt-2 text-xl font-bold">
               {renderModelName(status.embedding)}
            </div>
            <p className="text-xs text-muted-foreground mt-1" title={status.embedding.details?.base_url}>
              {status.embedding.configured ? status.embedding.details?.base_url : t("home.please_configure")}
            </p>
          </CardContent>
        </Card>
      </div>

      <h2 className="text-xl font-bold tracking-tight mt-4">{t("home.kg_analytics")}</h2>
      <div className="grid gap-6 md:grid-cols-3">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">{t("home.entities")}</CardTitle>
            <Database className="w-4 h-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{status.graph.entity_count.toLocaleString()}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">{t("home.relations")}</CardTitle>
            <Server className="w-4 h-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{status.graph.relation_count.toLocaleString()}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">{t("home.sources")}</CardTitle>
            <Database className="w-4 h-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{status.graph.source_count.toLocaleString()}</div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
