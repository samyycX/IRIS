import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronLeft, Plus, Trash, ShieldCheck } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Checkbox } from "@/components/ui/checkbox"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { apiFetch } from '@/lib/auth'

interface SearchPermissionSource {
  id: string;
  kind: 'api_key' | 'ip';
  description: string;
  enabled: boolean;
  allow_builtin_embedding: boolean;
  key_prefix?: string | null;
  ip_value?: string | null;
}

interface SearchApiConfig {
  enabled: boolean;
  validation_enabled: boolean;
  permission_sources: SearchPermissionSource[];
}

async function readErrorDetail(response: Response, fallback: string) {
  try {
    const data = await response.json();
    if (typeof data?.detail === 'string' && data.detail) {
      return data.detail;
    }
  } catch {
    // Ignore parsing errors and fall back to the provided message.
  }
  return fallback;
}

export default function SearchApiAuth() {
  const { t } = useTranslation();
  const [config, setConfig] = useState<{ search_api: SearchApiConfig } | null>(null);
  const [loading, setLoading] = useState(true);
  
  const [generatedSearchApiKey, setGeneratedSearchApiKey] = useState<string | null>(null);
  
  const [newApiKeyPermission, setNewApiKeyPermission] = useState<Partial<SearchPermissionSource>>({
    kind: 'api_key',
    description: '',
    enabled: true,
    allow_builtin_embedding: false,
  });

  const [newIpPermission, setNewIpPermission] = useState<Partial<SearchPermissionSource>>({
    kind: 'ip',
    description: '',
    enabled: true,
    allow_builtin_embedding: false,
    ip_value: '',
  });

  const fetchConfig = async () => {
    try {
      const res = await apiFetch('/api/config');
      if (!res.ok) {
        throw new Error(await readErrorDetail(res, 'Failed to load configuration'));
      }
      const data = await res.json();
      setConfig(data);
    } catch (err) {
      console.error(err);
      alert(err instanceof Error ? err.message : 'Failed to load configuration');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchConfig();
  }, []);

  const createSearchPermissionSource = async (sourceContent: Partial<SearchPermissionSource>) => {
    const payload: Record<string, unknown> = {
      kind: sourceContent.kind,
      description: sourceContent.description,
      enabled: sourceContent.enabled,
      allow_builtin_embedding: sourceContent.allow_builtin_embedding,
    };
    if (sourceContent.kind === 'ip') {
      payload.ip_value = sourceContent.ip_value || '';
    }
    try {
      const response = await apiFetch('/api/config/search-api/permissions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        alert(await readErrorDetail(response, 'Failed to create permission source'));
        return;
      }
      const data = await response.json();
      if (sourceContent.kind === 'api_key') {
        setGeneratedSearchApiKey(data.generated_api_key || null);
        setNewApiKeyPermission({
          kind: 'api_key',
          description: '',
          enabled: true,
          allow_builtin_embedding: false,
        });
      } else {
        setNewIpPermission({
          kind: 'ip',
          description: '',
          enabled: true,
          allow_builtin_embedding: false,
          ip_value: '',
        });
      }
      fetchConfig();
    } catch (err) {
      console.error(err);
      alert(err instanceof Error ? err.message : 'Failed to create permission source');
    }
  };

  const updateSearchPermissionSource = async (
    source: SearchPermissionSource,
    patch: Partial<SearchPermissionSource>
  ) => {
    try {
      const response = await apiFetch(`/api/config/search-api/permissions/${source.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          description: patch.description ?? source.description,
          enabled: patch.enabled ?? source.enabled,
          allow_builtin_embedding: patch.allow_builtin_embedding ?? source.allow_builtin_embedding,
          ip_value: patch.ip_value ?? source.ip_value ?? null,
        }),
      });
      if (!response.ok) {
        throw new Error(await readErrorDetail(response, 'Failed to update permission source'));
      }
      fetchConfig();
    } catch (err) {
      console.error(err);
      alert(err instanceof Error ? err.message : 'Failed to update permission source');
    }
  };

  const deleteSearchPermissionSource = async (id: string) => {
    try {
      const response = await apiFetch(`/api/config/search-api/permissions/${id}`, {
        method: 'DELETE',
      });
      if (!response.ok) {
        throw new Error(await readErrorDetail(response, 'Failed to delete permission source'));
      }
      fetchConfig();
    } catch (err) {
      console.error(err);
      alert(err instanceof Error ? err.message : 'Failed to delete permission source');
    }
  };

  if (loading || !config) {
    return <div className="text-sm text-muted-foreground">{t('auth.loading')}</div>;
  }

  const apiKeys = config.search_api.permission_sources.filter(s => s.kind === 'api_key');
  const ipSources = config.search_api.permission_sources.filter(s => s.kind === 'ip');

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      <div className="flex items-center space-x-4">
        <Link to="/config" className="flex h-9 w-9 items-center justify-center rounded-md hover:bg-accent hover:text-accent-foreground">
          <ChevronLeft className="h-5 w-5" />
        </Link>
        <div>
          <h1 className="text-2xl font-bold">{t('config.search_api_auth_sources_title')}</h1>
          <p className="text-sm text-muted-foreground">{t('config.search_api_auth_sources_desc')}</p>
        </div>
      </div>

      {/* API Keys Section */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-primary" />
            {t('config.search_api_auth_apikey_title')}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="rounded-lg border bg-muted/20 p-4 space-y-4">
            <div className="grid grid-cols-1 gap-4">
              <div className="grid gap-2">
                <Label>{t('config.search_api_permission_description')}</Label>
                <Input
                  value={newApiKeyPermission.description || ''}
                  onChange={(e) => setNewApiKeyPermission({ ...newApiKeyPermission, description: e.target.value })}
                  placeholder={t('config.search_api_permission_description_placeholder')}
                />
              </div>
            </div>
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div className="flex items-center space-x-2">
                <Checkbox
                  id="new_apikey_permission_allow_builtin_embedding"
                  checked={newApiKeyPermission.allow_builtin_embedding}
                  onCheckedChange={(checked) => setNewApiKeyPermission({ ...newApiKeyPermission, allow_builtin_embedding: !!checked })}
                />
                <Label htmlFor="new_apikey_permission_allow_builtin_embedding">{t('config.search_api_allow_builtin_embedding')}</Label>
              </div>
              <Button type="button" onClick={() => createSearchPermissionSource(newApiKeyPermission)}>
                <Plus className="w-4 h-4 mr-1" /> {t('config.search_api_permission_create')}
              </Button>
            </div>

            {generatedSearchApiKey && (
              <div className="mt-4 rounded-lg border border-primary/40 bg-primary/5 p-4">
                <div className="font-medium">{t('config.search_api_generated_key_title')}</div>
                <p className="mt-1 text-sm text-muted-foreground">{t('config.search_api_generated_key_desc')}</p>
                <div className="mt-3 rounded-md bg-background p-3 font-mono text-sm break-all">{generatedSearchApiKey}</div>
                <Button variant="outline" size="sm" className="mt-3" onClick={() => setGeneratedSearchApiKey(null)}>{t('runtime.ok', 'OK')}</Button>
              </div>
            )}
          </div>

          <div className="space-y-3">
            {apiKeys.length === 0 && (
              <p className="text-sm text-muted-foreground">{t('config.search_api_permission_empty')}</p>
            )}
            {apiKeys.map((source) => (
              <Card key={source.id} className="border shadow-sm">
                <CardContent className="pt-6 space-y-4">
                  <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                    <div className="space-y-1.5">
                      <div className="flex items-center gap-2">
                        <span className="font-medium">{source.description || source.key_prefix || source.id}</span>
                        <Badge variant="secondary">API Key</Badge>
                        {!source.enabled && <Badge variant="outline">{t('config.search_api_permission_disabled')}</Badge>}
                      </div>
                      <p className="text-sm text-muted-foreground">{source.description || t('config.search_api_permission_no_description')}</p>
                      {source.key_prefix && (
                        <p className="text-xs font-mono text-muted-foreground bg-muted w-fit px-1.5 py-0.5 rounded">{t('config.search_api_permission_prefix')}: {source.key_prefix}</p>
                      )}
                    </div>
                    <Button variant="ghost" size="icon" className="text-destructive" onClick={() => deleteSearchPermissionSource(source.id)}>
                      <Trash className="w-4 h-4" />
                    </Button>
                  </div>
                  <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                    <div className="flex items-center space-x-2">
                      <Checkbox
                        id={`apikey_enabled_${source.id}`}
                        checked={source.enabled}
                        onCheckedChange={(checked) => updateSearchPermissionSource(source, { enabled: !!checked })}
                      />
                      <Label htmlFor={`apikey_enabled_${source.id}`}>{t('config.search_api_permission_enabled')}</Label>
                    </div>
                    <div className="flex items-center space-x-2">
                      <Checkbox
                        id={`apikey_builtin_${source.id}`}
                        checked={source.allow_builtin_embedding}
                        onCheckedChange={(checked) => updateSearchPermissionSource(source, { allow_builtin_embedding: !!checked })}
                      />
                      <Label htmlFor={`apikey_builtin_${source.id}`}>{t('config.search_api_allow_builtin_embedding')}</Label>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* IP Whitelist Section */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-primary" />
            {t('config.search_api_auth_ip_title')}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="rounded-lg border bg-muted/20 p-4 space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="grid gap-2">
                <Label>{t('config.search_api_permission_ip')}</Label>
                <Input
                  value={newIpPermission.ip_value || ''}
                  onChange={(e) => setNewIpPermission({ ...newIpPermission, ip_value: e.target.value })}
                  placeholder={t('config.search_api_permission_ip_placeholder')}
                />
              </div>
              <div className="grid gap-2">
                <Label>{t('config.search_api_permission_description')}</Label>
                <Input
                  value={newIpPermission.description || ''}
                  onChange={(e) => setNewIpPermission({ ...newIpPermission, description: e.target.value })}
                  placeholder={t('config.search_api_permission_description_placeholder')}
                />
              </div>
            </div>
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div className="flex items-center space-x-2">
                <Checkbox
                  id="new_ip_permission_allow_builtin_embedding"
                  checked={newIpPermission.allow_builtin_embedding}
                  onCheckedChange={(checked) => setNewIpPermission({ ...newIpPermission, allow_builtin_embedding: !!checked })}
                />
                <Label htmlFor="new_ip_permission_allow_builtin_embedding">{t('config.search_api_allow_builtin_embedding')}</Label>
              </div>
              <Button type="button" onClick={() => createSearchPermissionSource(newIpPermission)} disabled={!newIpPermission.ip_value}>
                <Plus className="w-4 h-4 mr-1" /> {t('config.search_api_permission_create')}
              </Button>
            </div>
          </div>

          <div className="space-y-3">
            {ipSources.length === 0 && (
              <p className="text-sm text-muted-foreground">{t('config.search_api_permission_empty')}</p>
            )}
            {ipSources.map((source) => (
              <Card key={source.id} className="border shadow-sm">
                <CardContent className="pt-6 space-y-4">
                  <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                    <div className="space-y-1.5">
                      <div className="flex items-center gap-2">
                        <span className="font-medium">{source.description || source.ip_value || source.id}</span>
                        <Badge variant="secondary">IP</Badge>
                        {!source.enabled && <Badge variant="outline">{t('config.search_api_permission_disabled')}</Badge>}
                      </div>
                      <p className="text-sm text-muted-foreground">{source.description || t('config.search_api_permission_no_description')}</p>
                      {source.ip_value && (
                        <p className="text-xs font-mono text-muted-foreground bg-muted w-fit px-1.5 py-0.5 rounded">{t('config.search_api_permission_ip')}: {source.ip_value}</p>
                      )}
                    </div>
                    <Button variant="ghost" size="icon" className="text-destructive" onClick={() => deleteSearchPermissionSource(source.id)}>
                      <Trash className="w-4 h-4" />
                    </Button>
                  </div>
                  <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                    <div className="flex items-center space-x-2">
                      <Checkbox
                        id={`ip_enabled_${source.id}`}
                        checked={source.enabled}
                        onCheckedChange={(checked) => updateSearchPermissionSource(source, { enabled: !!checked })}
                      />
                      <Label htmlFor={`ip_enabled_${source.id}`}>{t('config.search_api_permission_enabled')}</Label>
                    </div>
                    <div className="flex items-center space-x-2">
                      <Checkbox
                        id={`ip_builtin_${source.id}`}
                        checked={source.allow_builtin_embedding}
                        onCheckedChange={(checked) => updateSearchPermissionSource(source, { allow_builtin_embedding: !!checked })}
                      />
                      <Label htmlFor={`ip_builtin_${source.id}`}>{t('config.search_api_allow_builtin_embedding')}</Label>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
