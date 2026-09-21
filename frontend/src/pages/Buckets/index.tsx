import type { CSSProperties } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Button, Form, Input, InputNumber, List, message, Popconfirm, Segmented, Select, Table } from 'antd'
import { AppstoreOutlined, CloseOutlined, CloudServerOutlined, DatabaseOutlined, DeleteOutlined, PlusOutlined, ReloadOutlined, RightOutlined, UnorderedListOutlined } from '@ant-design/icons'
import { bucketsApi, BucketInfo, BucketTag } from '../../api/buckets'
import { settingsApi, BucketStorageStat } from '../../api/settings'
import { providersApi, StorageProvider } from '../../api/providers'
import { useAuthStore } from '../../store/auth'
import BucketBrowser from '../../components/BucketBrowser'
import { C, mono, PageHeader, EditDrawer, ProviderChip, FilterBar, TagEditor, TagBadges } from '../../components/ui'
import dayjs from 'dayjs'

function formatBytes(bytes: number) {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`
}

// Returns fill ratio 0..1 (or null when no quota) and the bar color for that ratio.
function usageBar(sizeBytes: number, quotaBytes: number) {
  if (!quotaBytes || quotaBytes <= 0) return { ratio: null as number | null, color: C.dim }
  const ratio = Math.min(sizeBytes / quotaBytes, 1)
  const color = ratio >= 0.9 ? C.danger : ratio >= 0.75 ? C.warning : C.accent
  return { ratio, color }
}

const chipStyle: CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 8, ...mono, fontSize: 12,
  background: C.accentSoftBg, border: `1px solid ${C.accentSoftBorder}`, color: C.accentHover,
  borderRadius: 8, padding: '4px 10px',
}
const chipCloseStyle: CSSProperties = { cursor: 'pointer', fontSize: 11, opacity: 0.8 }

export default function BucketsPage() {
  const { bucketName } = useParams<{ bucketName?: string }>()
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const [buckets, setBuckets] = useState<BucketInfo[]>([])
  const [providers, setProviders] = useState<StorageProvider[]>([])
  const [bucketStats, setBucketStats] = useState<Record<string, BucketStorageStat>>({})
  const [suggest, setSuggest] = useState<Record<string, string[]>>({})
  const [loading, setLoading] = useState(true)
  const [createOpen, setCreateOpen] = useState(false)
  const [createLoading, setCreateLoading] = useState(false)
  const [createTags, setCreateTags] = useState<BucketTag[]>([])
  const [viewMode, setViewMode] = useState<'grid' | 'list'>(() => (localStorage.getItem('bucketView') as 'grid' | 'list') || 'grid')
  const [providerFilter, setProviderFilter] = useState<string>('all')
  // Tag query builder: a list of {key, values[]} filters, ANDed together.
  const [tagFilters, setTagFilters] = useState<{ key: string; values: string[] }[]>([])
  const [draftKey, setDraftKey] = useState<string | undefined>(undefined)
  const [draftValues, setDraftValues] = useState<string[]>([])
  const [search, setSearch] = useState('')
  const [form] = Form.useForm()

  const setView = (v: 'grid' | 'list') => { setViewMode(v); localStorage.setItem('bucketView', v) }

  const load = useCallback(() => {
    setLoading(true)
    bucketsApi.list().then((res) => {
      setBuckets(res.data)
      setLoading(false)
    })
    if (user?.is_admin) {
      settingsApi.getStorageStats().then((res) => {
        const map: Record<string, BucketStorageStat> = {}
        for (const b of res.data.buckets) map[b.name] = b
        setBucketStats(map)
      }).catch(() => {})
      providersApi.list().then((res) => setProviders(res.data)).catch(() => {})
      bucketsApi.suggestTags().then((res) => setSuggest(res.data)).catch(() => {})
    }
  }, [user?.is_admin])

  useEffect(() => { load() }, [load])

  const openCreate = () => { form.resetFields(); setCreateTags([]); setCreateOpen(true) }

  const handleCreate = async (values: { name: string; quota_gb?: number; provider_id?: string }) => {
    setCreateLoading(true)
    try {
      await bucketsApi.create(values.name, values.quota_gb, values.provider_id, createTags)
      message.success(`Bucket '${values.name}' created`)
      setCreateOpen(false)
      form.resetFields()
      setCreateTags([])
      load()
    } catch (e: any) {
      message.error(e.response?.data?.detail || 'Failed to create bucket')
    } finally {
      setCreateLoading(false)
    }
  }

  const handleDelete = async (name: string) => {
    try {
      await bucketsApi.deleteBucket(name)
      message.success(`Bucket '${name}' deleted`)
      load()
    } catch (e: any) {
      message.error(e.response?.data?.detail || 'Failed to delete bucket')
    }
  }

  const selected = buckets.find((b) => b.name === bucketName)

  // ── Filter options (must be computed before any early return) ────────────
  const providerOptions = useMemo(() => Array.from(
    new Map(buckets.filter((b) => b.provider_id).map((b) => [b.provider_id as string, b.provider_name as string])).entries()
  ).map(([value, label]) => ({ value, label })), [buckets])
  const hasUnassigned = buckets.some((b) => !b.provider_id)

  // Distinct tag keys and, per key, distinct values across all buckets.
  const tagKeys = useMemo(() => {
    const keys = new Set<string>()
    for (const b of buckets) for (const t of b.tags || []) keys.add(t.key)
    return Array.from(keys).sort()
  }, [buckets])
  const valuesForKey = (key?: string) => {
    if (!key) return [] as string[]
    const vals = new Set<string>()
    for (const b of buckets) for (const t of b.tags || []) if (t.key === key && t.value) vals.add(t.value)
    return Array.from(vals).sort()
  }

  const addTagFilter = () => {
    if (!draftKey) return
    setTagFilters((prev) => [...prev.filter((f) => f.key !== draftKey), { key: draftKey, values: draftValues }])
    setDraftKey(undefined); setDraftValues([])
  }
  const removeTagFilter = (key: string) => setTagFilters((prev) => prev.filter((f) => f.key !== key))
  const resetFilters = () => { setTagFilters([]); setDraftKey(undefined); setDraftValues([]); setProviderFilter('all'); setSearch('') }

  const visibleBuckets = useMemo(() => buckets.filter((b) => {
    if (search && !b.name.toLowerCase().includes(search.toLowerCase())) return false
    if (providerFilter === 'none' && b.provider_id) return false
    if (providerFilter !== 'all' && providerFilter !== 'none' && b.provider_id !== providerFilter) return false
    const tags = b.tags || []
    for (const f of tagFilters) {
      const matching = tags.filter((t) => t.key === f.key)
      if (matching.length === 0) return false
      // If specific values are chosen, the bucket must have one of them; else key presence is enough.
      if (f.values.length > 0 && !matching.some((t) => f.values.includes(t.value))) return false
    }
    return true
  }), [buckets, search, providerFilter, tagFilters])

  // Bucket detail view
  if (bucketName && selected) {
    return (
      <div className="animate-fade-in">
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 24 }}>
          <Button
            type="text"
            onClick={() => navigate('/buckets')}
            style={{ color: C.dim, padding: '0 4px', height: 'auto', fontWeight: 500, ...mono, fontSize: 13 }}
          >
            ~/buckets
          </Button>
          <span style={{ color: C.dim, ...mono }}>/</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ width: 22, height: 22, borderRadius: 5, background: C.accent, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <DatabaseOutlined style={{ color: '#0C0D10', fontSize: 11 }} />
            </div>
            <span style={{ color: C.text, fontWeight: 600, fontSize: 15, ...mono }}>{bucketName}</span>
          </div>
        </div>
        <BucketBrowser bucket={bucketName} canWrite={selected.can_write} canDelete={selected.can_delete} />
      </div>
    )
  }

  // Cards stay grouped by provider; flat list uses a Provider column instead.
  const groupMap = new Map<string, { key: string; name: string; items: BucketInfo[] }>()
  for (const b of visibleBuckets) {
    const key = b.provider_id || 'none'
    if (!groupMap.has(key)) groupMap.set(key, { key, name: b.provider_name || 'No provider', items: [] })
    groupMap.get(key)!.items.push(b)
  }
  const groups = Array.from(groupMap.values()).sort((a, b) => {
    if (a.key === 'none') return 1
    if (b.key === 'none') return -1
    return a.name.localeCompare(b.name)
  })

  const providerTypeOf = (b: BucketInfo) => providers.find((p) => p.id === b.provider_id)?.provider_type

  const gridRenderItem = (bucket: BucketInfo, idx: number) => {
    const stats = bucketStats[bucket.name]
    const staggerClass = `stagger-${Math.min(idx + 1, 6)}`
    const size = stats?.size ?? 0
    const quota = stats?.quota_bytes ?? 0
    const { ratio, color } = usageBar(size, quota)
    return (
      <List.Item>
        <div
          className={`animate-fade-up ${staggerClass}`}
          onClick={() => navigate(`/buckets/${bucket.name}`)}
          style={{
            background: C.surface,
            border: `1px solid ${C.border}`, borderRadius: 0, padding: 22, cursor: 'pointer',
            transition: 'border-color 180ms ease',
            position: 'relative', overflow: 'hidden',
            minHeight: 232, display: 'flex', flexDirection: 'column',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.borderColor = 'var(--border-strong, #363A42)'
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.borderColor = C.border
          }}
        >
          {/* Header */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 13, marginBottom: 18 }}>
            <div style={{
              width: 50, height: 50, borderRadius: 4,
              background: C.accent,
              display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
            }}>
              <DatabaseOutlined style={{ color: '#0C0D10', fontSize: 22 }} />
            </div>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ color: C.text, fontWeight: 600, fontSize: 16, ...mono, wordBreak: 'break-all', lineHeight: 1.3 }}>
                {bucket.name}
              </div>
            </div>
            {user?.is_admin ? (
              <Popconfirm
                title={`Delete '${bucket.name}'?`} description="Bucket must be empty."
                onConfirm={(e) => { e?.stopPropagation(); handleDelete(bucket.name) }}
                onCancel={(e) => e?.stopPropagation()}
              >
                <Button type="text" danger size="small" icon={<DeleteOutlined />} onClick={(e) => e.stopPropagation()} style={{ opacity: 0.5 }} />
              </Popconfirm>
            ) : (
              <RightOutlined style={{ color: C.dim, fontSize: 13 }} />
            )}
          </div>

          {/* Usage */}
          <div style={{ marginBottom: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8 }}>
              <span style={{ color: C.muted, fontSize: 13, ...mono }}>Usage</span>
              <span style={{ color: C.text, fontSize: 14, ...mono }}>
                {formatBytes(size)}{quota > 0 ? ` / ${formatBytes(quota)}` : ''}
              </span>
            </div>
            <div style={{ height: 8, borderRadius: 999, background: C.raised, overflow: 'hidden' }}>
              {ratio !== null && (
                <div style={{ width: `${Math.max(ratio * 100, 2)}%`, height: '100%', background: color, borderRadius: 999, transition: 'width 300ms ease' }} />
              )}
            </div>
          </div>

          <div style={{ height: 1, background: C.raised, margin: '0 0 16px' }} />

          {/* Objects + tags, pinned to the bottom for equal alignment */}
          <div style={{ marginTop: 'auto', display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{ flexShrink: 0 }}>
              <div style={{ color: C.dim, fontSize: 10, letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 3 }}>Objects</div>
              <div style={{ color: C.text, fontSize: 16, ...mono }}>{stats ? stats.object_count.toLocaleString() : '—'}</div>
            </div>
            <div style={{ marginLeft: 'auto', minWidth: 0, display: 'flex', justifyContent: 'flex-end' }}>
              {bucket.tags && bucket.tags.length > 0
                ? <TagBadges tags={bucket.tags} max={2} overflow="popover" />
                : null}
            </div>
          </div>
        </div>
      </List.Item>
    )
  }

  const listColumns = [
    {
      title: 'Name', dataIndex: 'name', key: 'name',
      render: (v: string) => (
        <span style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ width: 30, height: 30, borderRadius: 8, background: C.accentSoftBg, border: `1px solid ${C.accentSoftBorder}`, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', color: C.accentHover }}>
            <DatabaseOutlined style={{ fontSize: 14 }} />
          </span>
          <span style={{ ...mono, fontSize: 13, color: C.text }}>{v}</span>
        </span>
      ),
    },
    {
      title: 'Provider', key: 'provider', width: 190,
      render: (_: any, b: BucketInfo) => <ProviderChip name={b.provider_name} type={providerTypeOf(b)} />,
    },
    {
      title: 'Tags', key: 'tags',
      render: (_: any, b: BucketInfo) => <TagBadges tags={b.tags} max={3} />,
    },
    { title: 'Created', dataIndex: 'creation_date', key: 'created', width: 150, render: (v: string | null) => <span style={{ ...mono, fontSize: 12, color: C.muted }}>{v ? dayjs(v).format('MMM D, YYYY') : '—'}</span> },
    { title: 'Size', key: 'size', width: 110, render: (_: any, b: BucketInfo) => { const s = bucketStats[b.name]; return <span style={{ ...mono, fontSize: 12, color: C.muted }}>{s ? formatBytes(s.size) : '—'}</span> } },
    { title: 'Objects', key: 'objects', width: 90, render: (_: any, b: BucketInfo) => { const s = bucketStats[b.name]; return <span style={{ ...mono, fontSize: 12, color: C.muted }}>{s ? s.object_count : '—'}</span> } },
    ...(user?.is_admin ? [{
      title: '', key: 'actions', width: 56,
      render: (_: any, b: BucketInfo) => (
        <Popconfirm title={`Delete '${b.name}'?`} description="Bucket must be empty."
          onConfirm={(e) => { e?.stopPropagation(); handleDelete(b.name) }} onCancel={(e) => e?.stopPropagation()}>
          <Button type="text" danger size="small" icon={<DeleteOutlined />} onClick={(e) => e.stopPropagation()} />
        </Popconfirm>
      ),
    }] : []),
  ]

  const ProviderHeading = ({ name, count }: { name: string; count: number }) => (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, margin: '4px 0 16px' }}>
      <div style={{ width: 34, height: 34, borderRadius: 9, background: C.accentSoftBg, border: `1px solid ${C.accentSoftBorder}`, display: 'flex', alignItems: 'center', justifyContent: 'center', color: C.accentHover }}>
        <CloudServerOutlined style={{ fontSize: 17 }} />
      </div>
      <span style={{ color: C.text, fontWeight: 700, fontSize: 17 }}>{name}</span>
      <span style={{ ...mono, color: C.muted, fontSize: 11, letterSpacing: '0.06em', background: C.raised, border: `1px solid ${C.border}`, borderRadius: 6, padding: '3px 9px' }}>
        {count} BUCKET{count === 1 ? '' : 'S'}
      </span>
      <div style={{ flex: 1, height: 1, background: C.raised }} />
    </div>
  )

  const openCreateForProvider = (providerId?: string) => {
    form.resetFields()
    setCreateTags([])
    if (providerId) form.setFieldValue('provider_id', providerId)
    setCreateOpen(true)
  }

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="Buckets"
        subtitle={`${visibleBuckets.length} of ${buckets.length} bucket${buckets.length !== 1 ? 's' : ''}`}
        actions={user?.is_admin && (
          <Button icon={<PlusOutlined />} type="primary" onClick={openCreate} style={{ fontWeight: 600, height: 40 }}>
            Create New Bucket
          </Button>
        )}
      />

      <FilterBar search={search} onSearch={setSearch} placeholder="Search buckets…">
        {(providerOptions.length > 0 || hasUnassigned) && (
          <Select
            value={providerFilter}
            onChange={setProviderFilter}
            style={{ minWidth: 180 }}
            suffixIcon={<CloudServerOutlined />}
            options={[
              { value: 'all', label: 'All providers' },
              ...providerOptions,
              ...(hasUnassigned ? [{ value: 'none', label: 'No provider' }] : []),
            ]}
          />
        )}
        {tagKeys.length > 0 && (
          <>
            <Select
              showSearch
              allowClear
              value={draftKey}
              onChange={(k) => { setDraftKey(k); setDraftValues([]) }}
              placeholder="Tag key"
              style={{ minWidth: 140 }}
              options={tagKeys.map((k) => ({ value: k, label: k }))}
            />
            <Select
              mode="multiple"
              allowClear
              value={draftValues}
              onChange={setDraftValues}
              placeholder={draftKey ? 'Any value' : 'Value(s)'}
              disabled={!draftKey}
              style={{ minWidth: 180, maxWidth: 260 }}
              options={valuesForKey(draftKey).map((v) => ({ value: v, label: v }))}
            />
            <Button icon={<PlusOutlined />} onClick={addTagFilter} disabled={!draftKey}>Add</Button>
          </>
        )}
        <Segmented
          value={viewMode}
          onChange={(v) => setView(v as 'grid' | 'list')}
          options={[
            { value: 'grid', icon: <AppstoreOutlined /> },
            { value: 'list', icon: <UnorderedListOutlined /> },
          ]}
          style={{ background: C.surface, border: `1px solid ${C.border}`, padding: 3 }}
        />
      </FilterBar>

      {(tagFilters.length > 0 || providerFilter !== 'all' || search) && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginTop: -6, marginBottom: 16 }}>
          <span style={{ color: C.dim, fontSize: 12 }}>Active filters:</span>
          {providerFilter !== 'all' && (
            <span style={chipStyle}>
              provider: {providerFilter === 'none' ? 'none' : (providerOptions.find((p) => p.value === providerFilter)?.label || providerFilter)}
              <CloseOutlined onClick={() => setProviderFilter('all')} style={chipCloseStyle} />
            </span>
          )}
          {tagFilters.map((f) => (
            <span key={f.key} style={chipStyle}>
              {f.key}{f.values.length ? `: ${f.values.join(', ')}` : ' (any)'}
              <CloseOutlined onClick={() => removeTagFilter(f.key)} style={chipCloseStyle} />
            </span>
          ))}
          <Button size="small" icon={<ReloadOutlined />} onClick={resetFilters}>Reset filters</Button>
        </div>
      )}

      {loading ? (
        <List loading grid={{ gutter: 16, xs: 1, sm: 2, md: 2, lg: 3, xl: 3, xxl: 4 }} dataSource={[]} renderItem={() => null} />
      ) : visibleBuckets.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '60px 0', color: C.dim }}>
          <DatabaseOutlined style={{ fontSize: 32, marginBottom: 12, opacity: 0.5 }} />
          <div>{buckets.length === 0 ? 'No buckets yet.' : 'No buckets match the current filters.'}</div>
        </div>
      ) : viewMode === 'list' ? (
        <Table
          rowKey="name"
          dataSource={visibleBuckets}
          pagination={false}
          onRow={(bucket) => ({ onClick: () => navigate(`/buckets/${bucket.name}`), style: { cursor: 'pointer' } })}
          columns={listColumns}
        />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
          {groups.map((g) => (
            <div key={g.key}>
              <ProviderHeading name={g.name} count={g.items.length} />
              <List
                grid={{ gutter: 16, xs: 1, sm: 2, md: 2, lg: 3, xl: 3, xxl: 4 }}
                dataSource={user?.is_admin ? [...g.items, { __createTile: true } as unknown as BucketInfo] : g.items}
                renderItem={(item, idx) =>
                  (item as any).__createTile ? (
                    <List.Item key="__create">
                      <div
                        onClick={() => openCreateForProvider(g.key === 'none' ? undefined : g.key)}
                        style={{
                          minHeight: 232, borderRadius: 16, border: `1.5px dashed ${C.border}`,
                          display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                          gap: 12, cursor: 'pointer', color: C.muted,
                          transition: 'border-color 180ms ease, color 180ms ease',
                        }}
                        onMouseEnter={(e) => { e.currentTarget.style.borderColor = C.accentHover; e.currentTarget.style.color = C.accentHover }}
                        onMouseLeave={(e) => { e.currentTarget.style.borderColor = C.border; e.currentTarget.style.color = C.muted }}
                      >
                        <PlusOutlined style={{ fontSize: 26 }} />
                        <span style={{ fontSize: 15, fontWeight: 500 }}>Create New Bucket</span>
                      </div>
                    </List.Item>
                  ) : gridRenderItem(item, idx)
                }
              />
            </div>
          ))}
        </div>
      )}

      <EditDrawer
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="Create New Bucket"
        onSubmit={() => form.submit()}
        submitLabel="Create Bucket"
        submitLoading={createLoading}
      >
        <Form form={form} layout="vertical" onFinish={handleCreate} requiredMark={false}>
          <Form.Item
            name="name"
            label={<span style={{ fontSize: 13, color: C.muted }}>Bucket Name</span>}
            rules={[
              { required: true, message: 'Bucket name is required' },
              { pattern: /^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$/, message: 'Lowercase letters, numbers, dots, hyphens. 3-63 chars.' },
            ]}
          >
            <Input placeholder="my-bucket-name" size="large" style={{ ...mono, fontSize: 13 }} />
          </Form.Item>
          <Form.Item
            name="quota_gb"
            label={<span style={{ fontSize: 13, color: C.muted }}>Quota (GB) — optional</span>}
          >
            <InputNumber min={0.1} step={1} placeholder="e.g. 50" style={{ width: '100%', ...mono, fontSize: 13 }} size="large" />
          </Form.Item>
          <Form.Item
            name="provider_id"
            label={<span style={{ fontSize: 13, color: C.muted }}>Storage Provider</span>}
            extra={providers.length === 0 ? <span style={{ fontSize: 12, color: C.dim }}>No providers configured — the default connection will be used.</span> : undefined}
          >
            <Select
              size="large"
              allowClear
              placeholder={providers.length ? 'Use default provider' : 'Default connection'}
              disabled={providers.length === 0}
              options={providers.map((p) => ({
                value: p.id,
                label: `${p.name}${p.is_default ? ' (default)' : ''} · ${p.provider_type}`,
              }))}
            />
          </Form.Item>
          <div style={{ marginTop: 4 }}>
            <TagEditor value={createTags} onChange={setCreateTags} suggest={suggest} />
          </div>
        </Form>
      </EditDrawer>
    </div>
  )
}
