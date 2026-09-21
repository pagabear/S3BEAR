import React, { useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Input,
  message,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import { CopyOutlined, DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { ApiToken, tokensApi, TokenCreateResponse } from '../../api/tokens'
import { C, mono, PageHeader, EditDrawer, RowActions } from '../../components/ui'

const EXPIRY_OPTIONS = [
  { label: '30 days', value: '30d' },
  { label: '90 days', value: '90d' },
  { label: '1 year', value: '365d' },
  { label: 'Never', value: 'never' },
]

function statusTag(t: ApiToken): React.ReactNode {
  if (t.revoked) return <Tag color="red" style={{ ...mono, fontSize: 11 }}>revoked</Tag>
  if (t.expires_at && dayjs(t.expires_at).isBefore(dayjs())) {
    return <Tag color="volcano" style={{ ...mono, fontSize: 11 }}>expired</Tag>
  }
  return <Tag color="green" style={{ ...mono, fontSize: 11 }}>active</Tag>
}

export default function TokensPage() {
  const [data, setData] = useState<ApiToken[]>([])
  const [loading, setLoading] = useState(true)
  const [createOpen, setCreateOpen] = useState(false)
  const [name, setName] = useState('')
  const [expiresIn, setExpiresIn] = useState('never')
  const [creating, setCreating] = useState(false)
  const [created, setCreated] = useState<TokenCreateResponse | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const res = await tokensApi.list()
      setData(res.data)
    } catch {
      message.error('Failed to load tokens')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const handleCreate = async () => {
    if (!name.trim()) {
      message.error('Token name is required')
      return
    }
    setCreating(true)
    try {
      const res = await tokensApi.create(name.trim(), expiresIn)
      setCreated(res.data)
      setName('')
      setExpiresIn('never')
      load()
    } catch {
      message.error('Failed to create token')
    } finally {
      setCreating(false)
    }
  }

  const handleRevoke = async (id: string) => {
    try {
      await tokensApi.revoke(id)
      message.success('Token revoked')
      load()
    } catch {
      message.error('Failed to revoke token')
    }
  }

  const closeCreate = () => {
    setCreateOpen(false)
    setCreated(null)
    setName('')
    setExpiresIn('never')
  }

  const columns = [
    { title: 'status', key: 'status', width: 90, render: (_: unknown, t: ApiToken) => statusTag(t) },
    {
      title: 'name',
      dataIndex: 'name',
      key: 'name',
      render: (v: string) => <span style={{ ...mono, fontSize: 12 }}>{v}</span>,
    },
    {
      title: 'prefix',
      dataIndex: 'token_prefix',
      key: 'token_prefix',
      width: 180,
      render: (v: string) => <span style={{ ...mono, fontSize: 11, color: '#9AA0AA' }}>{v}…</span>,
    },
    {
      title: 'expires',
      dataIndex: 'expires_at',
      key: 'expires_at',
      width: 150,
      render: (v: string | null) => (
        <span style={{ ...mono, fontSize: 11, color: '#9AA0AA' }}>
          {v ? dayjs(v).format('YYYY-MM-DD') : 'never'}
        </span>
      ),
    },
    {
      title: 'last used',
      dataIndex: 'last_used_at',
      key: 'last_used_at',
      width: 150,
      render: (v: string | null) => (
        <span style={{ ...mono, fontSize: 11, color: '#9AA0AA' }}>
          {v ? dayjs(v).format('YYYY-MM-DD HH:mm') : 'never'}
        </span>
      ),
    },
    {
      title: '',
      key: 'actions',
      width: 56,
      render: (_: unknown, t: ApiToken) =>
        t.revoked ? null : (
          <RowActions actions={[
            { key: 'revoke', label: 'Revoke', icon: <DeleteOutlined />, danger: true, confirm: 'Revoke this token? Any client using it stops working immediately.', onClick: () => handleRevoke(t.id) },
          ]} />
        ),
    },
  ]

  return (
    <div>
      <PageHeader
        title="Tokens"
        subtitle="Personal access tokens act as you and inherit your permissions."
        actions={<Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>New token</Button>}
      />

      <Table
        rowKey="id"
        columns={columns}
        dataSource={data}
        loading={loading}
        size="small"
        pagination={{ pageSize: 50 }}
      />

      <EditDrawer
        open={createOpen}
        onClose={closeCreate}
        title="New API token"
        onSubmit={created ? undefined : handleCreate}
        submitLabel="Create"
        submitLoading={creating}
        hideFooter={!!created}
      >
        {!created ? (
          <Space direction="vertical" style={{ width: '100%' }} size={14}>
            <div>
              <div style={{ color: C.muted, fontSize: 11, ...mono, marginBottom: 4 }}>name</div>
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. ci-pipeline"
                style={{ ...mono, fontSize: 12 }}
              />
            </div>
            <div>
              <div style={{ color: C.muted, fontSize: 11, ...mono, marginBottom: 4 }}>expires</div>
              <Select value={expiresIn} onChange={setExpiresIn} options={EXPIRY_OPTIONS} style={{ width: '100%' }} />
            </div>
          </Space>
        ) : (
          <Space direction="vertical" style={{ width: '100%' }} size={12}>
            <Alert
              type="warning"
              showIcon
              message="Copy your token now"
              description="This is the only time the token is shown. Store it somewhere safe — you cannot retrieve it again."
            />
            <Space.Compact style={{ width: '100%' }}>
              <Input value={created.token} readOnly style={{ ...mono, fontSize: 12 }} />
              <Button
                icon={<CopyOutlined />}
                onClick={async () => {
                  await navigator.clipboard.writeText(created.token)
                  message.success('Token copied')
                }}
              >
                Copy
              </Button>
            </Space.Compact>
            <Typography.Text type="secondary" style={{ ...mono, fontSize: 11 }}>
              Use it as a Bearer token: <code>Authorization: Bearer {created.token_prefix}…</code>
            </Typography.Text>
            <Button type="primary" block onClick={closeCreate} style={{ marginTop: 4 }}>Done</Button>
          </Space>
        )}
      </EditDrawer>
    </div>
  )
}
