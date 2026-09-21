import React, { useEffect, useState } from 'react'
import { DatePicker, Select, Space, Table, Tag } from 'antd'
import { auditApi, AuditEntry, AuditFilters } from '../../api/audit'
import { PageHeader } from '../../components/ui'
import dayjs from 'dayjs'

const ACTION_COLORS: Record<string, string> = {
  upload: 'green',
  delete: 'red',
  download: 'blue',
  create_bucket: 'cyan',
  delete_bucket: 'volcano',
  user_create: 'purple',
  user_delete: 'magenta',
  permission_change: 'orange',
  copy: 'geekblue',
  move: 'gold',
  cleanup: 'lime',
  share_create: 'green',
  share_revoke: 'red',
  token_create: 'green',
  token_revoke: 'red',
  webhook_create: 'cyan',
  webhook_update: 'blue',
  webhook_delete: 'red',
}

const ACTION_OPTIONS = [
  'upload', 'delete', 'download', 'create_bucket', 'delete_bucket',
  'user_create', 'user_delete', 'permission_change', 'copy', 'move', 'cleanup',
  'share_create', 'share_revoke', 'token_create', 'token_revoke',
  'webhook_create', 'webhook_update', 'webhook_delete',
]

export default function AuditLogPage() {
  const [data, setData] = useState<AuditEntry[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [filters, setFilters] = useState<AuditFilters>({ page: 1, page_size: 50 })

  const load = async (f: AuditFilters) => {
    setLoading(true)
    try {
      const res = await auditApi.list(f)
      setData(res.data.items)
      setTotal(res.data.total)
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load(filters) }, [filters])

  const updateFilter = (key: string, value: any) => {
    setFilters((prev) => ({ ...prev, [key]: value, page: 1 }))
  }

  const columns = [
    {
      title: 'time',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 160,
      render: (v: string) => (
        <span style={{ fontFamily: "'Fira Code', monospace", fontSize: 11, color: '#9AA0AA' }}>
          {dayjs(v).format('YYYY-MM-DD HH:mm:ss')}
        </span>
      ),
    },
    {
      title: 'user',
      dataIndex: 'user_email',
      key: 'user_email',
      width: 200,
      ellipsis: true,
      render: (v: string) => (
        <span style={{ fontFamily: "'Fira Code', monospace", fontSize: 12 }}>{v}</span>
      ),
    },
    {
      title: 'action',
      dataIndex: 'action',
      key: 'action',
      width: 140,
      render: (v: string) => (
        <Tag color={ACTION_COLORS[v] || 'default'} style={{ fontFamily: "'Fira Code', monospace", fontSize: 11 }}>
          {v}
        </Tag>
      ),
    },
    {
      title: 'bucket',
      dataIndex: 'bucket',
      key: 'bucket',
      width: 150,
      render: (v: string | null) => v ? (
        <span style={{ fontFamily: "'Fira Code', monospace", fontSize: 12 }}>{v}</span>
      ) : <span style={{ color: '#656B75' }}>—</span>,
    },
    {
      title: 'object',
      dataIndex: 'object_key',
      key: 'object_key',
      ellipsis: true,
      render: (v: string | null) => v ? (
        <span style={{ fontFamily: "'Fira Code', monospace", fontSize: 11, color: '#CBD5E1' }}>{v}</span>
      ) : <span style={{ color: '#656B75' }}>—</span>,
    },
    {
      title: 'ip',
      dataIndex: 'ip_address',
      key: 'ip_address',
      width: 130,
      render: (v: string | null) => (
        <span style={{ fontFamily: "'Fira Code', monospace", fontSize: 11, color: '#656B75' }}>{v || '—'}</span>
      ),
    },
  ]

  return (
    <div>
      <PageHeader title="Logs" subtitle={`${total} event${total !== 1 ? 's' : ''}`} />

      {/* Filters */}
      <Space wrap style={{ marginBottom: 16 }}>
        <Select
          allowClear
          placeholder="action"
          style={{ width: 160 }}
          onChange={(v) => updateFilter('action', v)}
          options={ACTION_OPTIONS.map((a) => ({ label: a, value: a }))}
        />
        <Select
          allowClear
          placeholder="bucket"
          style={{ width: 160 }}
          showSearch
          onChange={(v) => updateFilter('bucket', v)}
          options={[...new Set(data.map((d) => d.bucket).filter(Boolean))].map((b) => ({ label: b, value: b }))}
        />
        <DatePicker.RangePicker
          onChange={(dates) => {
            if (dates && dates[0] && dates[1]) {
              updateFilter('date_from', dates[0].toISOString())
              setFilters((prev) => ({ ...prev, date_to: dates[1]!.toISOString(), page: 1 }))
            } else {
              setFilters((prev) => {
                const { date_from, date_to, ...rest } = prev
                return { ...rest, page: 1 }
              })
            }
          }}
        />
      </Space>

      <Table
        rowKey="id"
        columns={columns}
        dataSource={data}
        loading={loading}
        size="small"
        pagination={{
          current: filters.page,
          pageSize: filters.page_size,
          total,
          showSizeChanger: true,
          pageSizeOptions: ['25', '50', '100'],
          onChange: (page, pageSize) => setFilters((prev) => ({ ...prev, page, page_size: pageSize })),
        }}
        expandable={{
          expandedRowRender: (record) => record.details ? (
            <pre style={{ fontFamily: "'Fira Code', monospace", fontSize: 11, color: '#9AA0AA', margin: 0 }}>
              {JSON.stringify(record.details, null, 2)}
            </pre>
          ) : null,
          rowExpandable: (record) => !!record.details,
        }}
      />
    </div>
  )
}
