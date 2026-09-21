import React, { useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Drawer,
  Input,
  message,
  Select,
  Space,
  Switch,
  Table,
  Tag,
} from 'antd'
import { CopyOutlined, DeleteOutlined, PlusOutlined, SendOutlined, UnorderedListOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  Webhook,
  WebhookCreateResponse,
  WebhookDelivery,
  WEBHOOK_EVENTS,
  webhooksApi,
} from '../../api/webhooks'
import { C, mono, PageHeader, EditDrawer, RowActions } from '../../components/ui'

const DELIVERY_COLORS: Record<string, string> = {
  success: 'green',
  pending: 'gold',
  failed: 'red',
}

export default function WebhooksPage() {
  const [data, setData] = useState<Webhook[]>([])
  const [loading, setLoading] = useState(true)
  const [createOpen, setCreateOpen] = useState(false)
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [events, setEvents] = useState<string[]>([])
  const [creating, setCreating] = useState(false)
  const [created, setCreated] = useState<WebhookCreateResponse | null>(null)
  const [deliveriesFor, setDeliveriesFor] = useState<Webhook | null>(null)
  const [deliveries, setDeliveries] = useState<WebhookDelivery[]>([])

  const load = async () => {
    setLoading(true)
    try {
      setData((await webhooksApi.list()).data)
    } catch {
      message.error('Failed to load webhooks')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const handleCreate = async () => {
    if (!name.trim() || !url.trim() || events.length === 0) {
      message.error('Name, URL, and at least one event are required')
      return
    }
    setCreating(true)
    try {
      const res = await webhooksApi.create(name.trim(), url.trim(), events)
      setCreated(res.data)
      setName(''); setUrl(''); setEvents([])
      load()
    } catch (e: any) {
      message.error(e?.response?.data?.detail?.[0]?.msg || 'Failed to create webhook')
    } finally {
      setCreating(false)
    }
  }

  const closeCreate = () => {
    setCreateOpen(false); setCreated(null); setName(''); setUrl(''); setEvents([])
  }

  const toggleEnabled = async (w: Webhook, enabled: boolean) => {
    try {
      await webhooksApi.update(w.id, { enabled })
      load()
    } catch {
      message.error('Failed to update')
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await webhooksApi.remove(id)
      message.success('Webhook deleted')
      load()
    } catch {
      message.error('Failed to delete')
    }
  }

  const handleTest = async (w: Webhook) => {
    try {
      await webhooksApi.test(w.id)
      message.success('Test event queued — it will be delivered within ~20s')
    } catch {
      message.error('Failed to queue test')
    }
  }

  const openDeliveries = async (w: Webhook) => {
    setDeliveriesFor(w)
    try {
      setDeliveries((await webhooksApi.deliveries(w.id)).data)
    } catch {
      setDeliveries([])
    }
  }

  const columns = [
    {
      title: 'enabled',
      key: 'enabled',
      width: 80,
      render: (_: unknown, w: Webhook) => (
        <Switch size="small" checked={w.enabled} onChange={(v) => toggleEnabled(w, v)} />
      ),
    },
    {
      title: 'name',
      dataIndex: 'name',
      key: 'name',
      width: 150,
      render: (v: string) => <span style={{ ...mono, fontSize: 12 }}>{v}</span>,
    },
    {
      title: 'url',
      dataIndex: 'url',
      key: 'url',
      ellipsis: true,
      render: (v: string) => <span style={{ ...mono, fontSize: 11, color: '#CBD5E1' }}>{v}</span>,
    },
    {
      title: 'events',
      dataIndex: 'events',
      key: 'events',
      width: 220,
      render: (evs: string[]) => (
        <Space size={2} wrap>
          {evs.map((e) => <Tag key={e} style={{ ...mono, fontSize: 10 }}>{e}</Tag>)}
        </Space>
      ),
    },
    {
      title: '',
      key: 'actions',
      width: 56,
      render: (_: unknown, w: Webhook) => (
        <RowActions actions={[
          { key: 'test', label: 'Send test', icon: <SendOutlined />, onClick: () => handleTest(w) },
          { key: 'deliveries', label: 'Deliveries', icon: <UnorderedListOutlined />, onClick: () => openDeliveries(w) },
          { key: 'delete', label: 'Delete', icon: <DeleteOutlined />, danger: true, confirm: 'Delete this webhook?', onClick: () => handleDelete(w.id) },
        ]} />
      ),
    },
  ]

  const deliveryColumns = [
    { title: 'event', dataIndex: 'event', key: 'event', width: 110, render: (v: string) => <span style={{ ...mono, fontSize: 11 }}>{v}</span> },
    { title: 'status', dataIndex: 'status', key: 'status', width: 90, render: (v: string) => <Tag color={DELIVERY_COLORS[v]} style={{ ...mono, fontSize: 10 }}>{v}</Tag> },
    { title: 'attempts', dataIndex: 'attempts', key: 'attempts', width: 80, render: (v: number) => <span style={{ ...mono, fontSize: 11 }}>{v}</span> },
    { title: 'code', dataIndex: 'last_status_code', key: 'code', width: 70, render: (v: number | null) => <span style={{ ...mono, fontSize: 11, color: '#9AA0AA' }}>{v ?? '—'}</span> },
    { title: 'error', dataIndex: 'last_error', key: 'error', ellipsis: true, render: (v: string | null) => <span style={{ ...mono, fontSize: 10, color: '#EF4444' }}>{v || ''}</span> },
    { title: 'time', dataIndex: 'created_at', key: 'time', width: 150, render: (v: string) => <span style={{ ...mono, fontSize: 11, color: '#9AA0AA' }}>{dayjs(v).format('MM-DD HH:mm:ss')}</span> },
  ]

  return (
    <div>
      <PageHeader
        title="Webhooks"
        subtitle="HTTP callbacks on state-changing events, signed with HMAC-SHA256."
        actions={<Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>New webhook</Button>}
      />

      <Table rowKey="id" columns={columns} dataSource={data} loading={loading} size="small" pagination={false} />

      <EditDrawer
        open={createOpen}
        onClose={closeCreate}
        title="New webhook"
        onSubmit={created ? undefined : handleCreate}
        submitLabel="Create"
        submitLoading={creating}
        hideFooter={!!created}
      >
        {!created ? (
          <Space direction="vertical" style={{ width: '100%' }} size={14}>
            <div>
              <div style={{ color: C.muted, fontSize: 11, ...mono, marginBottom: 4 }}>name</div>
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. indexer" style={{ ...mono, fontSize: 12 }} />
            </div>
            <div>
              <div style={{ color: C.muted, fontSize: 11, ...mono, marginBottom: 4 }}>url</div>
              <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://example.com/hook" style={{ ...mono, fontSize: 12 }} />
            </div>
            <div>
              <div style={{ color: C.muted, fontSize: 11, ...mono, marginBottom: 4 }}>events</div>
              <Select
                mode="multiple"
                value={events}
                onChange={setEvents}
                style={{ width: '100%' }}
                placeholder="select events"
                options={WEBHOOK_EVENTS.map((e) => ({ label: e, value: e }))}
              />
            </div>
          </Space>
        ) : (
          <Space direction="vertical" style={{ width: '100%' }} size={12}>
            <Alert
              type="warning"
              showIcon
              message="Copy your signing secret now"
              description="This is the only time the secret is shown. Use it to verify the X-S3Bear-Signature header on incoming deliveries."
            />
            <Space.Compact style={{ width: '100%' }}>
              <Input value={created.secret} readOnly style={{ ...mono, fontSize: 12 }} />
              <Button
                icon={<CopyOutlined />}
                onClick={async () => { await navigator.clipboard.writeText(created.secret); message.success('Secret copied') }}
              >
                Copy
              </Button>
            </Space.Compact>
            <Button type="primary" block onClick={closeCreate} style={{ marginTop: 4 }}>Done</Button>
          </Space>
        )}
      </EditDrawer>

      <Drawer
        title={deliveriesFor ? `Deliveries — ${deliveriesFor.name}` : 'Deliveries'}
        open={!!deliveriesFor}
        onClose={() => setDeliveriesFor(null)}
        width={760}
      >
        <Table rowKey="id" columns={deliveryColumns} dataSource={deliveries} size="small" pagination={{ pageSize: 25 }} />
      </Drawer>
    </div>
  )
}
