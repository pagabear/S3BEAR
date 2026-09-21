import { useEffect, useMemo, useState } from 'react'
import { Button, InputNumber, message, Progress, Select, Space, Table, Tag, Tooltip } from 'antd'
import {
  CloudServerOutlined, DatabaseOutlined, EditOutlined, PlayCircleOutlined, ReloadOutlined,
} from '@ant-design/icons'
import { settingsApi, StorageStats } from '../../api/settings'
import { providersApi, StorageProvider } from '../../api/providers'
import { policiesApi, CleanupPolicy } from '../../api/admin'
import { C, mono, PageHeader, ProviderChip, FilterBar } from '../../components/ui'
import dayjs from 'dayjs'

function formatBytes(bytes: number) {
  if (!bytes || bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`
}
const bytesToGb = (b: number) => Math.round((b / (1024 ** 3)) * 100) / 100

const POLICY_STATUS_COLOR: Record<string, string> = { success: 'green', failed: 'red', running: 'gold' }

function StatTile({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ flex: '1 1 160px', background: C.surface, border: `1px solid ${C.border}`, borderRadius: 12, padding: '16px 18px' }}>
      <div style={{ color: C.dim, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</div>
      <div style={{ ...mono, color: C.text, fontSize: 22, marginTop: 4 }}>{value}</div>
    </div>
  )
}

export default function ObservabilityPage() {
  const [storage, setStorage] = useState<StorageStats | null>(null)
  const [providers, setProviders] = useState<StorageProvider[]>([])
  const [policies, setPolicies] = useState<CleanupPolicy[]>([])
  const [loading, setLoading] = useState(true)
  const [providerFilter, setProviderFilter] = useState<string>('all')
  const [editGlobal, setEditGlobal] = useState(false)
  const [globalVal, setGlobalVal] = useState(0)
  const [editBucket, setEditBucket] = useState<string | null>(null)
  const [bucketVal, setBucketVal] = useState(0)

  const load = () => {
    setLoading(true)
    Promise.all([
      settingsApi.getStorageStats().then((r) => { setStorage(r.data); setGlobalVal(bytesToGb(r.data.quota_bytes)) }).catch(() => {}),
      providersApi.list().then((r) => setProviders(r.data)).catch(() => {}),
      policiesApi.list().then((r) => setPolicies(r.data)).catch(() => {}),
    ]).finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [])

  const providerOptions = useMemo(() => {
    const seen = new Map<string, string>()
    for (const b of storage?.buckets || []) if (b.provider_id) seen.set(b.provider_id, b.provider_name || b.provider_id)
    return Array.from(seen.entries()).map(([value, label]) => ({ value, label }))
  }, [storage])

  const providerTypeOf = (id?: string | null) => providers.find((p) => p.id === id)?.provider_type

  const buckets = useMemo(() => {
    const all = storage?.buckets || []
    if (providerFilter === 'all') return all
    if (providerFilter === 'none') return all.filter((b) => !b.provider_id)
    return all.filter((b) => b.provider_id === providerFilter)
  }, [storage, providerFilter])

  // Recompute totals for the current provider scope.
  const scope = useMemo(() => {
    const size = buckets.reduce((s, b) => s + b.size, 0)
    const objects = buckets.reduce((s, b) => s + b.object_count, 0)
    return { size, objects, count: buckets.length }
  }, [buckets])

  const saveGlobal = async () => {
    try { await settingsApi.updateGlobalQuota(globalVal); message.success('Global quota updated'); setEditGlobal(false); load() }
    catch (e: any) { message.error(e.response?.data?.detail || 'Failed') }
  }
  const saveBucket = async () => {
    if (!editBucket) return
    try { await settingsApi.updateBucketQuota(editBucket, bucketVal); message.success('Quota updated'); setEditBucket(null); load() }
    catch (e: any) { message.error(e.response?.data?.detail || 'Failed') }
  }
  const runPolicy = async (id: string) => {
    try { const r = await policiesApi.run(id); message.success(`Run complete: deleted ${(r.data as any).deleted_count ?? 0} objects`); load() }
    catch { message.error('Run failed') }
  }

  const globalPct = storage && storage.quota_bytes > 0 ? Math.min(100, Math.round((storage.total_size / storage.quota_bytes) * 100)) : 0

  const bucketColumns = [
    { title: 'Bucket', dataIndex: 'name', key: 'name', render: (v: string) => <span style={{ ...mono, fontSize: 12, color: C.text }}><DatabaseOutlined style={{ marginRight: 6, color: C.accentHover }} />{v}</span> },
    { title: 'Provider', key: 'provider', width: 170, render: (_: any, r: any) => <ProviderChip name={r.provider_name} type={providerTypeOf(r.provider_id)} /> },
    { title: 'Size', dataIndex: 'size', key: 'size', width: 110, render: (v: number) => <span style={{ ...mono, fontSize: 12, color: C.muted }}>{formatBytes(v)}</span>, sorter: (a: any, b: any) => a.size - b.size },
    { title: 'Objects', dataIndex: 'object_count', key: 'oc', width: 90, render: (v: number) => <span style={{ ...mono, fontSize: 12, color: C.muted }}>{v}</span> },
    {
      title: 'Quota', key: 'quota', width: 170,
      render: (_: any, r: any) => {
        if (editBucket === r.name) return (
          <Space size={4}><InputNumber size="small" min={0} step={0.5} value={bucketVal} onChange={(v) => setBucketVal(v || 0)} style={{ width: 70 }} />
            <Button size="small" type="primary" onClick={saveBucket}>OK</Button><Button size="small" onClick={() => setEditBucket(null)}>✕</Button></Space>
        )
        const q = r.quota_bytes > 0 ? bytesToGb(r.quota_bytes) : 0
        return <Space size={6}><span style={{ color: C.muted }}>{q > 0 ? `${q} GB` : 'No limit'}</span>
          <Tooltip title="Edit quota"><Button type="text" size="small" icon={<EditOutlined />} onClick={() => { setEditBucket(r.name); setBucketVal(q) }} /></Tooltip></Space>
      },
    },
    {
      title: 'Usage', key: 'usage', width: 170,
      render: (_: any, r: any) => {
        if (r.quota_bytes > 0) { const p = Math.min(100, Math.round((r.size / r.quota_bytes) * 100)); return <Progress percent={p} size="small" status={p >= 90 ? 'exception' : 'normal'} /> }
        const p = scope.size > 0 ? Math.round((r.size / scope.size) * 100) : 0
        return <Progress percent={p} size="small" strokeColor="#656B75" />
      },
    },
  ]

  const policyColumns = [
    { title: 'Policy', dataIndex: 'name', key: 'name', render: (v: string) => <span style={{ color: C.text, fontWeight: 600 }}>{v}</span> },
    { title: 'Target', key: 'target', render: (_: any, r: CleanupPolicy) => r.target_type === 'tag'
      ? <Tag color="purple" style={{ ...mono, fontSize: 10 }}>tag: {r.tag_key}{r.tag_value ? `=${r.tag_value}` : ' (any)'}</Tag>
      : <Space size={4} wrap>{r.bucket_patterns.map((p) => <Tag key={p} style={{ ...mono, fontSize: 10 }}>{p}</Tag>)}</Space> },
    { title: 'Schedule', dataIndex: 'cron_expression', key: 'cron', width: 130, render: (v: string) => <span style={{ ...mono, fontSize: 11, color: C.muted }}>{v}</span> },
    {
      title: 'Active', dataIndex: 'is_active', key: 'active', width: 80,
      render: (v: boolean) => <Tag color={v ? 'green' : 'default'} style={{ ...mono, fontSize: 10 }}>{v ? 'active' : 'off'}</Tag>,
    },
    {
      title: 'Last run', key: 'lastrun', width: 200,
      render: (_: any, r: CleanupPolicy) => r.last_run_at ? (
        <Space size={6}>
          <Tag color={POLICY_STATUS_COLOR[r.last_run_status || ''] || 'default'} style={{ ...mono, fontSize: 10 }}>{r.last_run_status || 'unknown'}</Tag>
          <span style={{ ...mono, fontSize: 11, color: C.dim }}>{dayjs(r.last_run_at).format('MMM D HH:mm')}</span>
          {r.last_run_deleted_count != null && <span style={{ ...mono, fontSize: 11, color: C.dim }}>· {r.last_run_deleted_count} del</span>}
        </Space>
      ) : <span style={{ color: C.dim, fontSize: 12 }}>never run</span>,
    },
    {
      title: '', key: 'run', width: 90,
      render: (_: any, r: CleanupPolicy) => <Button size="small" icon={<PlayCircleOutlined />} onClick={() => runPolicy(r.id)}>Run</Button>,
    },
  ]

  const activePolicies = policies.filter((p) => p.is_active).length
  const failedRuns = policies.filter((p) => p.last_run_status === 'failed').length

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="Observability"
        subtitle="Storage usage, quotas, and cleanup activity across your providers."
        actions={<Button icon={<ReloadOutlined />} onClick={load} loading={loading}>Refresh</Button>}
      />

      <FilterBar>
        <span style={{ color: C.muted, fontSize: 13 }}>Provider</span>
        <Select
          value={providerFilter}
          onChange={setProviderFilter}
          style={{ minWidth: 200 }}
          suffixIcon={<CloudServerOutlined />}
          options={[
            { value: 'all', label: 'All providers' },
            ...providerOptions,
            ...((storage?.buckets || []).some((b) => !b.provider_id) ? [{ value: 'none', label: 'No provider' }] : []),
          ]}
        />
      </FilterBar>

      {/* Scope tiles */}
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginBottom: 16 }}>
        <StatTile label={providerFilter === 'all' ? 'Total used' : 'Used (scope)'} value={formatBytes(scope.size)} />
        <StatTile label="Objects" value={String(scope.objects)} />
        <StatTile label="Buckets" value={String(scope.count)} />
        <StatTile label="Global limit" value={storage && storage.quota_bytes > 0 ? formatBytes(storage.quota_bytes) : 'Unlimited'} />
        <StatTile label="Active policies" value={`${activePolicies}${failedRuns ? ` · ${failedRuns} failed` : ''}`} />
      </div>

      {/* Global limit bar */}
      {storage && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 20, padding: '12px 16px', background: C.raised, border: `1px solid ${C.border}`, borderRadius: 10 }}>
          <span style={{ color: C.text, fontWeight: 500 }}>Global storage limit</span>
          {editGlobal ? (
            <Space>
              <InputNumber min={0} step={1} value={globalVal} onChange={(v) => setGlobalVal(v || 0)} style={{ width: 120 }} addonAfter="GB" />
              <Button size="small" type="primary" onClick={saveGlobal}>Save</Button>
              <Button size="small" onClick={() => setEditGlobal(false)}>Cancel</Button>
              <span style={{ color: C.dim, fontSize: 12 }}>(0 = unlimited)</span>
            </Space>
          ) : (
            <Space>
              <span style={{ ...mono, color: C.muted }}>{storage.quota_bytes > 0 ? `${bytesToGb(storage.quota_bytes)} GB` : 'Unlimited'}</span>
              <Button size="small" icon={<EditOutlined />} onClick={() => setEditGlobal(true)}>Edit</Button>
            </Space>
          )}
          {storage.quota_bytes > 0 && <div style={{ flex: 1, minWidth: 140 }}><Progress percent={globalPct} status={globalPct >= 90 ? 'exception' : 'normal'} /></div>}
        </div>
      )}

      {/* Per-bucket usage */}
      <div style={{ ...mono, color: C.dim, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.08em', margin: '4px 0 10px' }}>Bucket usage</div>
      <Table rowKey="name" columns={bucketColumns} dataSource={buckets} pagination={false} size="small" loading={loading} style={{ marginBottom: 28 }} />

      {/* Policy activity */}
      <div style={{ ...mono, color: C.dim, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.08em', margin: '4px 0 10px' }}>Cleanup policy activity</div>
      <Table rowKey="id" columns={policyColumns} dataSource={policies} pagination={false} size="small" loading={loading}
        locale={{ emptyText: 'No cleanup policies configured.' }} />
    </div>
  )
}
