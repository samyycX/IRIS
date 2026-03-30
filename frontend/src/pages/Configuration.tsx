import React, { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, ChevronUp, Check, Plus, Trash, Edit, ShieldCheck, ShieldOff } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Checkbox } from "@/components/ui/checkbox"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"

interface Profile {
  id: string;
  uri?: string;
  username?: string;
  password?: string;
  base_url?: string;
  api_key?: string;
  model?: string;
}

interface Config {
  schema_version: number;
  neo4j_profiles: Profile[];
  active_neo4j_profile_id: string | null;
  llm_profiles: Profile[];
  active_llm_profile_id: string | null;
  embedding_profiles: Profile[];
  active_embedding_profile_id: string | null;
  runtime: Record<string, any>;
}

// Inline Collapsible Card
const CollapsibleCard: React.FC<{
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}> = ({ title, children, defaultOpen = true }) => {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  return (
    <Card className="mb-6">
      <CardHeader 
        className="cursor-pointer flex flex-row items-center justify-between" 
        onClick={() => setIsOpen(!isOpen)}
      >
        <CardTitle className="text-lg">{title}</CardTitle>
        {isOpen ? <ChevronUp className="w-5 h-5 text-muted-foreground" /> : <ChevronDown className="w-5 h-5 text-muted-foreground" />}
      </CardHeader>
      {isOpen && (
        <CardContent>
          {children}
        </CardContent>
      )}
    </Card>
  );
};

export default function Configuration() {
  const { t } = useTranslation();
  const [config, setConfig] = useState<Config | null>(null);
  const [loading, setLoading] = useState(true);
  const [newAllowedDomain, setNewAllowedDomain] = useState('');

  // Profile editing state
  const [editingProfile, setEditingProfile] = useState<{kind: string, profile: Profile, isNew: boolean} | null>(null);

  const fetchConfig = async () => {
    try {
      const res = await fetch('/api/config');
      const data = await res.json();
      setConfig(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchConfig();
  }, []);

  const updateRuntimeField = async (key: string, value: any) => {
    if (!config) return;
    const newConfig = {
      ...config,
      runtime: { ...config.runtime, [key]: value }
    };
    setConfig(newConfig); // optimistic update

    try {
      await fetch('/api/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newConfig)
      });
      fetchConfig();
    } catch (err) {
      console.error(err);
    }
  };

  // Profile Management
  const setActiveProfile = async (kind: string, id: string | null) => {
    try {
      if (id) {
        await fetch(`/api/config/data-sources/${kind}/active/${id}`, { method: 'PUT' });
      } else {
        await fetch(`/api/config/data-sources/${kind}/active`, { method: 'DELETE' });
      }
      fetchConfig();
    } catch (err) {
      console.error(err);
    }
  };

  const deleteProfile = async (kind: string, id: string) => {
    try {
      await fetch(`/api/config/data-sources/${kind}/${id}`, { method: 'DELETE' });
      fetchConfig();
    } catch (err) {
      console.error(err);
    }
  };

  const saveProfile = async (kind: string, profile: Profile, isNew: boolean) => {
    let payload: Record<string, unknown>;
    if (kind === 'neo4j') {
      payload = {
        id: profile.id,
        uri: String(profile.uri ?? ''),
        username: String(profile.username ?? ''),
        password: String(profile.password ?? ''),
      };
    } else if (kind === 'llm' || kind === 'embedding') {
      payload = {
        id: profile.id,
        base_url: String(profile.base_url ?? ''),
        api_key: String(profile.api_key ?? ''),
        model: String(profile.model ?? ''),
      };
    } else {
      payload = { ...profile } as Record<string, unknown>;
    }
    try {
      if (isNew) {
        await fetch(`/api/config/data-sources/${kind}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
      } else {
        await fetch(`/api/config/data-sources/${kind}/${profile.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
      }
      setEditingProfile(null);
      fetchConfig();
    } catch (err) {
      console.error(err);
    }
  };

  const normalizeDomain = (value: string) =>
    value.trim().toLowerCase().replace(/^https?:\/\//, '').split('/')[0];

  const addAllowedDomain = async () => {
    if (!config) return;
    const domain = normalizeDomain(newAllowedDomain);
    if (!domain) return;
    const nextDomains = Array.from(new Set([...(config.runtime.allowed_domains || []), domain]));
    setNewAllowedDomain('');
    await updateRuntimeField('allowed_domains', nextDomains);
  };

  const removeAllowedDomain = async (domain: string) => {
    if (!config) return;
    await updateRuntimeField(
      'allowed_domains',
      (config.runtime.allowed_domains || []).filter((item: string) => item !== domain)
    );
  };

  const toggleAllowedDomainsEnabled = async () => {
    if (!config) return;
    await updateRuntimeField('allowed_domains_enabled', !config.runtime.allowed_domains_enabled);
  };

  const renderProfileList = (kind: string, profiles: Profile[], activeId: string | null, titleKey: string) => {
    return (
      <div className="mb-6 space-y-4">
        <div className="flex justify-between items-center border-b pb-2">
          <h3 className="font-semibold">{t(titleKey)}</h3>
          <Button variant="outline" size="sm" onClick={() => setEditingProfile({ kind, profile: { id: '' }, isNew: true })}>
            <Plus className="w-4 h-4 mr-1" /> {t('config.add_profile')}
          </Button>
        </div>
        
        {editingProfile && editingProfile.kind === kind && (
          <Card className="bg-muted/50 border-primary">
            <CardContent className="pt-6 grid gap-4">
              <div className="grid gap-2">
                <Label>
                  {t('config.profile.id')} <span className="text-red-500">*</span>
                </Label>
                <Input 
                  value={editingProfile.profile.id} 
                  onChange={e => setEditingProfile({ ...editingProfile, profile: { ...editingProfile.profile, id: e.target.value } })}
                  disabled={!editingProfile.isNew}
                />
              </div>

              {kind === 'neo4j' && (
                <>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="grid gap-2">
                      <Label>{t('config.profile.uri')} <span className="text-red-500">*</span></Label>
                      <Input value={editingProfile.profile.uri || ''} onChange={e => setEditingProfile({ ...editingProfile, profile: { ...editingProfile.profile, uri: e.target.value } })} />
                    </div>
                    <div className="grid gap-2">
                      <Label>{t('config.profile.username')}</Label>
                      <Input value={editingProfile.profile.username || ''} onChange={e => setEditingProfile({ ...editingProfile, profile: { ...editingProfile.profile, username: e.target.value } })} />
                    </div>
                  </div>
                  <div className="grid gap-2">
                    <Label>{t('config.profile.password')}</Label>
                    <Input type="password" value={editingProfile.profile.password || ''} onChange={e => setEditingProfile({ ...editingProfile, profile: { ...editingProfile.profile, password: e.target.value } })} />
                  </div>
                </>
              )}

              {(kind === 'llm' || kind === 'embedding') && (
                <>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="grid gap-2">
                      <Label>{t('config.profile.base_url')}</Label>
                      <Input value={editingProfile.profile.base_url || ''} onChange={e => setEditingProfile({ ...editingProfile, profile: { ...editingProfile.profile, base_url: e.target.value } })} />
                    </div>
                    <div className="grid gap-2">
                      <Label>{t('config.profile.model')} <span className="text-red-500">*</span></Label>
                      <Input value={editingProfile.profile.model || ''} onChange={e => setEditingProfile({ ...editingProfile, profile: { ...editingProfile.profile, model: e.target.value } })} />
                    </div>
                  </div>
                  <div className="grid gap-2">
                    <Label>{t('config.profile.api_key')}</Label>
                    <Input type="password" value={editingProfile.profile.api_key || ''} onChange={e => setEditingProfile({ ...editingProfile, profile: { ...editingProfile.profile, api_key: e.target.value } })} />
                  </div>
                </>
              )}

              <div className="flex justify-end gap-2 mt-2">
                <Button variant="outline" onClick={() => setEditingProfile(null)}>{t('config.profile.cancel')}</Button>
                <Button onClick={() => saveProfile(kind, editingProfile.profile, editingProfile.isNew)}>{t('config.profile.save')}</Button>
              </div>
            </CardContent>
          </Card>
        )}

        <div className="grid gap-2">
          {profiles.length === 0 && <p className="text-sm text-muted-foreground italic">No profiles configured.</p>}
          {profiles.map(p => (
            <div key={p.id} className="flex items-center justify-between p-3 border rounded-md bg-card">
              <div className="flex items-center gap-3">
                <div className="font-medium">{p.id}</div>
                {activeId === p.id && <Badge variant="default" className="ml-2 flex items-center gap-1"><Check className="w-3 h-3" /> {t('config.active_badge')}</Badge>}
              </div>
              <div className="flex items-center gap-2">
                {activeId !== p.id && (
                  <Button variant="secondary" size="sm" onClick={() => setActiveProfile(kind, p.id)}>
                    {t('config.set_active')}
                  </Button>
                )}
                <Button variant="ghost" size="icon" onClick={() => setEditingProfile({ kind, profile: p, isNew: false })}>
                  <Edit className="w-4 h-4" />
                </Button>
                <Button variant="ghost" size="icon" className="text-destructive" onClick={() => deleteProfile(kind, p.id)} disabled={activeId === p.id}>
                  <Trash className="w-4 h-4" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  };

  if (loading || !config) return <div className="p-8">Loading configuration...</div>;

  return (
    <div className="max-w-4xl mx-auto py-6">
      <h1 className="text-2xl font-bold mb-6">{t('config.page_title')}</h1>

      <CollapsibleCard title={t('config.data_collection')}>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="grid gap-2 md:col-span-2">
            <Label>{t('runtime.knowledge_theme')}</Label>
            <Input 
              defaultValue={config.runtime.knowledge_theme} 
              onBlur={(e) => updateRuntimeField('knowledge_theme', e.target.value)} 
            />
            <span className="text-xs text-muted-foreground">{t('runtime.knowledge_theme_desc')}</span>
          </div>
          <div className="grid gap-2">
            <Label>{t('runtime.visited_url_ttl_days')}</Label>
            <Input 
              type="number" 
              defaultValue={config.runtime.visited_url_ttl_days} 
              onBlur={(e) => updateRuntimeField('visited_url_ttl_days', parseInt(e.target.value))} 
            />
            <span className="text-xs text-muted-foreground">{t('runtime.visited_url_ttl_days_desc')}</span>
          </div>
          <div className="grid gap-2">
            <Label>{t('runtime.request_timeout_seconds')}</Label>
            <Input 
              type="number" 
              defaultValue={config.runtime.request_timeout_seconds} 
              onBlur={(e) => updateRuntimeField('request_timeout_seconds', parseInt(e.target.value))} 
            />
            <span className="text-xs text-muted-foreground">{t('runtime.request_timeout_seconds_desc')}</span>
          </div>
          <div className="grid gap-2">
            <Label>{t('runtime.user_agent')}</Label>
            <Input 
              defaultValue={config.runtime.user_agent} 
              onBlur={(e) => updateRuntimeField('user_agent', e.target.value)} 
            />
            <span className="text-xs text-muted-foreground">{t('runtime.user_agent_desc')}</span>
          </div>
          <div className="grid gap-3 md:col-span-2 rounded-lg border bg-muted/30 p-4">
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div className="space-y-1">
                <Label>{t('runtime.allowed_domains')}</Label>
                <p className="text-xs text-muted-foreground">{t('runtime.allowed_domains_desc')}</p>
              </div>
              <Button
                type="button"
                variant={config.runtime.allowed_domains_enabled ? 'default' : 'outline'}
                onClick={toggleAllowedDomainsEnabled}
                className="gap-2 self-start"
              >
                {config.runtime.allowed_domains_enabled ? <ShieldCheck className="w-4 h-4" /> : <ShieldOff className="w-4 h-4" />}
                {config.runtime.allowed_domains_enabled ? t('runtime.allowed_domains_enabled_on') : t('runtime.allowed_domains_enabled_off')}
              </Button>
            </div>
            <div className="flex flex-col gap-3 md:flex-row">
              <Input
                value={newAllowedDomain}
                placeholder={t('runtime.allowed_domains_placeholder')}
                onChange={(e) => setNewAllowedDomain(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    addAllowedDomain();
                  }
                }}
              />
              <Button type="button" variant="secondary" onClick={addAllowedDomain}>
                <Plus className="w-4 h-4 mr-1" /> {t('runtime.allowed_domains_add')}
              </Button>
            </div>
            <div className="flex flex-wrap gap-2">
              {(config.runtime.allowed_domains || []).length === 0 && (
                <span className="text-sm text-muted-foreground">{t('runtime.allowed_domains_empty')}</span>
              )}
              {(config.runtime.allowed_domains || []).map((domain: string) => (
                <Badge key={domain} variant="secondary" className="flex items-center gap-2 px-3 py-1">
                  <span>{domain}</span>
                  <button
                    type="button"
                    className="rounded-sm text-muted-foreground transition-colors hover:text-destructive"
                    onClick={() => removeAllowedDomain(domain)}
                    aria-label={`${t('config.delete_profile')}: ${domain}`}
                  >
                    <Trash className="w-3 h-3" />
                  </button>
                </Badge>
              ))}
            </div>
          </div>
          <div className="flex items-center space-x-2 md:col-span-2 pt-2">
            <Checkbox 
              id="skip_history" 
              checked={config.runtime.skip_history_seen_urls} 
              onCheckedChange={(c) => updateRuntimeField('skip_history_seen_urls', !!c)} 
            />
            <div className="grid gap-1.5 leading-none">
              <Label htmlFor="skip_history">{t('runtime.skip_history_seen_urls')}</Label>
              <p className="text-xs text-muted-foreground">{t('runtime.skip_history_seen_urls_desc')}</p>
            </div>
          </div>
        </div>
      </CollapsibleCard>

      <CollapsibleCard title={t('config.db_strategy')}>
        {renderProfileList('neo4j', config.neo4j_profiles, config.active_neo4j_profile_id, 'config.profiles.neo4j')}
        <div className="border-t pt-4 mt-2">
          <div className="flex items-center space-x-2">
            <Checkbox 
              id="auto_backfill" 
              checked={config.runtime.auto_backfill_indexes_after_crawl} 
              onCheckedChange={(c) => updateRuntimeField('auto_backfill_indexes_after_crawl', !!c)} 
            />
            <div className="grid gap-1.5 leading-none">
              <Label htmlFor="auto_backfill">{t('runtime.auto_backfill_indexes_after_crawl')}</Label>
              <p className="text-xs text-muted-foreground">{t('runtime.auto_backfill_indexes_after_crawl_desc')}</p>
            </div>
          </div>
        </div>
      </CollapsibleCard>

      <CollapsibleCard title={t('config.models')}>
        {renderProfileList('llm', config.llm_profiles, config.active_llm_profile_id, 'config.profiles.llm')}
        <div className="border-t pb-4 mb-4"></div>
        {renderProfileList('embedding', config.embedding_profiles, config.active_embedding_profile_id, 'config.profiles.embedding')}
        
        <div className="border-t pt-4 mt-2 grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="grid gap-2">
            <Label>{t('runtime.llm_timeout_seconds')}</Label>
            <Input 
              type="number" 
              defaultValue={config.runtime.llm_timeout_seconds} 
              onBlur={(e) => updateRuntimeField('llm_timeout_seconds', parseInt(e.target.value))} 
            />
            <span className="text-xs text-muted-foreground">{t('runtime.llm_timeout_seconds_desc')}</span>
          </div>
          <div className="grid gap-2">
            <Label>{t('runtime.embedding_dimensions')}</Label>
            <Input 
              type="number" 
              defaultValue={config.runtime.embedding_dimensions} 
              onBlur={(e) => updateRuntimeField('embedding_dimensions', parseInt(e.target.value))} 
            />
            <span className="text-xs text-muted-foreground">{t('runtime.embedding_dimensions_desc')}</span>
          </div>
          <div className="grid gap-2">
            <Label>{t('runtime.embedding_batch_size')}</Label>
            <Input 
              type="number" 
              defaultValue={config.runtime.embedding_batch_size} 
              onBlur={(e) => updateRuntimeField('embedding_batch_size', parseInt(e.target.value))} 
            />
            <span className="text-xs text-muted-foreground">{t('runtime.embedding_batch_size_desc')}</span>
          </div>
          <div className="grid gap-2">
            <Label>{t('runtime.embedding_text_max_chars')}</Label>
            <Input 
              type="number" 
              defaultValue={config.runtime.embedding_text_max_chars} 
              onBlur={(e) => updateRuntimeField('embedding_text_max_chars', parseInt(e.target.value))} 
            />
            <span className="text-xs text-muted-foreground">{t('runtime.embedding_text_max_chars_desc')}</span>
          </div>
        </div>
      </CollapsibleCard>

      <CollapsibleCard title={t('config.browser')} defaultOpen={false}>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="md:col-span-2 rounded-lg border bg-muted/30 p-4 text-sm text-muted-foreground">
            {t('config.browser_note')}
          </div>
          <div className="flex items-center space-x-2 pt-2 md:col-span-2">
            <Checkbox 
              id="auto_accept" 
              checked={config.runtime.browser_auto_accept_consent} 
              onCheckedChange={(c) => updateRuntimeField('browser_auto_accept_consent', !!c)} 
            />
            <div className="grid gap-1.5 leading-none">
              <Label htmlFor="auto_accept">{t('runtime.browser_auto_accept_consent')}</Label>
              <p className="text-xs text-muted-foreground">{t('runtime.browser_auto_accept_consent_desc')}</p>
            </div>
          </div>

          <div className="grid gap-2">
            <Label>{t('runtime.browser_navigation_timeout_ms')}</Label>
            <Input 
              type="number" 
              defaultValue={config.runtime.browser_navigation_timeout_ms} 
              onBlur={(e) => updateRuntimeField('browser_navigation_timeout_ms', parseInt(e.target.value))} 
            />
            <span className="text-xs text-muted-foreground">{t('runtime.browser_navigation_timeout_ms_desc')}</span>
          </div>
          <div className="grid gap-2">
            <Label>{t('runtime.browser_post_load_wait_ms')}</Label>
            <Input 
              type="number" 
              defaultValue={config.runtime.browser_post_load_wait_ms} 
              onBlur={(e) => updateRuntimeField('browser_post_load_wait_ms', parseInt(e.target.value))} 
            />
            <span className="text-xs text-muted-foreground">{t('runtime.browser_post_load_wait_ms_desc')}</span>
          </div>
          <div className="grid gap-2">
            <Label>{t('runtime.browser_scroll_pause_ms')}</Label>
            <Input 
              type="number" 
              defaultValue={config.runtime.browser_scroll_pause_ms} 
              onBlur={(e) => updateRuntimeField('browser_scroll_pause_ms', parseInt(e.target.value))} 
            />
            <span className="text-xs text-muted-foreground">{t('runtime.browser_scroll_pause_ms_desc')}</span>
          </div>
          <div className="grid gap-2">
            <Label>{t('runtime.browser_scroll_rounds')}</Label>
            <Input 
              type="number" 
              defaultValue={config.runtime.browser_scroll_rounds} 
              onBlur={(e) => updateRuntimeField('browser_scroll_rounds', parseInt(e.target.value))} 
            />
            <span className="text-xs text-muted-foreground">{t('runtime.browser_scroll_rounds_desc')}</span>
          </div>
          <div className="grid gap-2">
            <Label>{t('runtime.browser_locale')}</Label>
            <Input 
              defaultValue={config.runtime.browser_locale} 
              onBlur={(e) => updateRuntimeField('browser_locale', e.target.value)} 
            />
            <span className="text-xs text-muted-foreground">{t('runtime.browser_locale_desc')}</span>
          </div>
        </div>
      </CollapsibleCard>

    </div>
  );
}
