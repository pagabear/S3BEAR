import React, { useEffect, useState } from 'react'
import {
  Button, Drawer, Empty, Form, Input, message, Popconfirm,
  Space, Spin, Switch, Tabs, Tag, Tooltip,
} from 'antd'
import {
  ApiOutlined, CloudOutlined, CloudServerOutlined, DatabaseOutlined,
  DeleteOutlined, EditOutlined, HddOutlined, LockOutlined, MailOutlined, PlusOutlined,
  SafetyOutlined, StarFilled, StarOutlined, WindowsFilled,
} from '@ant-design/icons'
import {
  AuthProvider, AzureAdConfig, settingsApi,
} from '../../api/settings'
import { providersApi, StorageProvider } from '../../api/providers'
import { PageHeader } from '../../components/ui'

/* ── helpers ─────────────────────────────────────────────────────────────── */
const mono = { fontFamily: "'Fira Code', monospace" }

function SectionTitle({ icon, title, subtitle, action }: { icon: React.ReactNode; title: string; subtitle?: string; action?: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 20, paddingBottom: 18, borderBottom: '1px solid #24242A' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, minWidth: 0 }}>
        <div style={{ width: 44, height: 44, borderRadius: 8, background: 'rgba(16,185,129,0.1)', border: '1px solid rgba(16,185,129,0.24)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#34D399', fontSize: 19, flexShrink: 0 }}>
          {icon}
        </div>
        <div style={{ minWidth: 0 }}>
          <div style={{ color: '#ECEEF1', fontWeight: 700, fontSize: 19 }}>{title}</div>
          {subtitle && <div style={{ color: '#9AA0AA', fontSize: 13, marginTop: 3 }}>{subtitle}</div>}
        </div>
      </div>
      {action && <div style={{ flexShrink: 0 }}>{action}</div>}
    </div>
  )
}

const fieldLabel = (t: string) => <span style={{ color: '#9AA0AA', fontSize: 13 }}>{t}</span>

/* ── Storage providers manager (multi-backend) ───────────────────────────── */
const PROVIDER_TYPE_LABEL: Record<string, string> = {
  aws: 'AWS S3', minio: 'MinIO', ceph: 'Ceph', wasabi: 'Wasabi', custom: 'Custom',
}
const PROVIDER_TYPE_ICON: Record<string, React.ReactNode> = {
  aws: <CloudOutlined />, minio: <HddOutlined />, ceph: <DatabaseOutlined />,
  wasabi: <CloudOutlined />, custom: <CloudServerOutlined />,
}

function StorageProviders() {
  const [providers, setProviders] = useState<StorageProvider[]>([])
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<StorageProvider | null>(null)
  const [ptype, setPtype] = useState('aws')
  const [useSsl, setUseSsl] = useState(true)
  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const load = () => {
    setLoading(true)
    providersApi.list().then((r) => setProviders(r.data)).catch(() => {}).finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [])

  const openCreate = () => {
    setEditing(null); setPtype('aws'); setUseSsl(true)
    form.resetFields()
    form.setFieldsValue({ region: 'us-east-1' })
    setOpen(true)
  }
  const openEdit = (p: StorageProvider) => {
    setEditing(p); setPtype(p.provider_type); setUseSsl(p.use_ssl)
    form.setFieldsValue({
      name: p.name, access_key_id: p.access_key_id, region: p.region || 'us-east-1',
      endpoint_url: p.endpoint_url, presigned_base: p.presigned_base, secret_access_key: '',
    })
    setOpen(true)
  }

  const buildPayload = (values: any) => ({
    name: values.name,
    provider_type: ptype,
    access_key_id: values.access_key_id,
    secret_access_key: values.secret_access_key || undefined,
    region: values.region || 'us-east-1',
    endpoint_url: ptype === 'aws' ? '' : (values.endpoint_url || ''),
    presigned_base: values.presigned_base || '',
    use_ssl: useSsl,
  })

  const handleTest = async () => {
    try {
      const values = await form.validateFields()
      setTesting(true)
      const res = await providersApi.test({ ...buildPayload(values), id: editing?.id })
      res.data.ok ? message.success('Connection successful') : message.error(res.data.error || 'Connection failed')
    } catch (e: any) { if (!e?.errorFields) message.error('Connection test failed') }
    finally { setTesting(false) }
  }

  const handleSave = async (values: any) => {
    setSaving(true)
    try {
      if (editing) {
        await providersApi.update(editing.id, buildPayload(values))
        message.success('Provider updated')
      } else {
        await providersApi.create({ ...buildPayload(values), is_default: providers.length === 0 } as any)
        message.success('Provider added')
      }
      setOpen(false); load()
    } catch (e: any) { message.error(e.response?.data?.detail || 'Failed to save provider') }
    finally { setSaving(false) }
  }

  const handleDelete = async (p: StorageProvider) => {
    try { await providersApi.remove(p.id); message.success(`Provider '${p.name}' deleted`); load() }
    catch (e: any) { message.error(e.response?.data?.detail || 'Failed to delete') }
  }
  const handleSetDefault = async (p: StorageProvider) => {
    try { await providersApi.setDefault(p.id); load() }
    catch (e: any) { message.error(e.response?.data?.detail || 'Failed') }
  }

  const showEndpoint = ptype !== 'aws'
  const editingSecret = !!editing && editing.has_secret

  return (
    <>
      <section>
        <SectionTitle
          icon={<CloudServerOutlined />}
          title="Storage providers"
          subtitle="Connections used to route and serve bucket data."
          action={<Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>Add provider</Button>}
        />

        {loading ? (
          <div style={{ display: 'grid', placeItems: 'center', minHeight: 220 }}><Spin /></div>
        ) : providers.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={<span style={{ color: '#9AA0AA' }}>No providers yet. Add one to route buckets to specific S3 backends.<br />Until then, the environment S3 config is used.</span>}
            style={{ padding: '64px 0', borderBottom: '1px solid #24242A' }}
          />
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12, paddingTop: 18 }}>
            {providers.map((p) => (
              <div key={p.id} style={{ display: 'flex', alignItems: 'center', gap: 16, background: '#121215', border: '1px solid #282C33', borderRadius: 8, padding: '18px 20px', boxShadow: '0 10px 28px rgba(0,0,0,0.16)' }}>
                <div style={{ width: 48, height: 48, borderRadius: 8, background: 'rgba(16,185,129,0.1)', border: '1px solid rgba(16,185,129,0.24)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#34D399', fontSize: 20, flexShrink: 0 }}>
                  {PROVIDER_TYPE_ICON[p.provider_type] || <CloudServerOutlined />}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
                    <span style={{ color: '#ECEEF1', fontWeight: 650, fontSize: 16 }}>{p.name}</span>
                    <Tag style={{ borderRadius: 6, margin: 0 }}>{PROVIDER_TYPE_LABEL[p.provider_type] || p.provider_type}</Tag>
                    {p.is_default && <Tag icon={<StarFilled />} color="gold" style={{ borderRadius: 6, margin: 0 }}>Default</Tag>}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 24, flexWrap: 'wrap' }}>
                    <div style={{ minWidth: 260, flex: 1 }}>
                      <div style={{ color: '#656B75', fontSize: 10, fontWeight: 600, textTransform: 'uppercase', marginBottom: 4 }}>Endpoint</div>
                      <div style={{ ...mono, color: '#9AA0AA', fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.endpoint_url || `https://s3.${p.region}.amazonaws.com`}</div>
                    </div>
                    <div>
                      <div style={{ color: '#656B75', fontSize: 10, fontWeight: 600, textTransform: 'uppercase', marginBottom: 4 }}>Region</div>
                      <div style={{ ...mono, color: '#9AA0AA', fontSize: 12 }}>{p.region}</div>
                    </div>
                    <div>
                      <div style={{ color: '#656B75', fontSize: 10, fontWeight: 600, textTransform: 'uppercase', marginBottom: 4 }}>Buckets</div>
                      <div style={{ ...mono, color: '#34D399', fontSize: 12 }}>{p.bucket_count}</div>
                    </div>
                  </div>
                </div>
                <Space size={4}>
                  {!p.is_default && (
                    <Tooltip title="Set as default">
                      <Button type="text" shape="circle" icon={<StarOutlined />} onClick={() => handleSetDefault(p)} />
                    </Tooltip>
                  )}
                  <Tooltip title="Edit">
                    <Button type="text" shape="circle" icon={<EditOutlined />} onClick={() => openEdit(p)} style={{ color: '#9AA0AA' }} />
                  </Tooltip>
                  <Popconfirm
                    title={`Delete '${p.name}'?`}
                    description={p.bucket_count > 0 ? 'This provider has buckets attached and cannot be deleted.' : 'This cannot be undone.'}
                    okButtonProps={{ danger: true, disabled: p.bucket_count > 0 }}
                    onConfirm={() => handleDelete(p)}
                  >
                    <Button type="text" danger size="small" icon={<DeleteOutlined />} />
                  </Popconfirm>
                </Space>
              </div>
            ))}
          </div>
        )}
      </section>

      <Drawer
        title={editing ? `Edit ${editing.name}` : 'Add Storage Provider'}
        open={open}
        onClose={() => setOpen(false)}
        width={460}
        destroyOnClose
      >
        <div style={{ color: '#9AA0AA', fontSize: 13, marginBottom: 20 }}>Register an S3-compatible backend. Buckets are bound to a provider when created.</div>

        <div style={{ color: '#9AA0AA', fontSize: 12, fontWeight: 600, letterSpacing: '0.06em', marginBottom: 8 }}>PROVIDER TYPE</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10, marginBottom: 22 }}>
          {[{ value: 'aws', label: 'AWS S3', icon: <CloudOutlined /> },
            { value: 'minio', label: 'MinIO', icon: <HddOutlined /> },
            { value: 'ceph', label: 'Ceph', icon: <DatabaseOutlined /> },
            { value: 'wasabi', label: 'Wasabi', icon: <CloudOutlined /> },
            { value: 'custom', label: 'Custom', icon: <CloudServerOutlined /> }].map((p) => {
            const active = ptype === p.value
            return (
              <div key={p.value} onClick={() => setPtype(p.value)} style={{
                cursor: 'pointer', textAlign: 'center', padding: '12px 6px', borderRadius: 10,
                background: active ? 'rgba(16,185,129,0.12)' : '#1C1E23',
                border: `1px solid ${active ? '#10B981' : '#282C33'}`,
                color: active ? '#34D399' : '#9AA0AA', transition: 'all 150ms ease',
              }}>
                <div style={{ fontSize: 18, marginBottom: 4 }}>{p.icon}</div>
                <div style={{ fontSize: 12, fontWeight: 500 }}>{p.label}</div>
              </div>
            )
          })}
        </div>

        <Form form={form} layout="vertical" onFinish={handleSave} requiredMark={false}>
          <Form.Item name="name" label={fieldLabel('Display Name')} rules={[{ required: true, message: 'Required' }]}>
            <Input prefix={<CloudServerOutlined style={{ color: '#656B75' }} />} placeholder="e.g. Production AWS, Local MinIO" style={{ height: 44 }} />
          </Form.Item>
          <Form.Item name="access_key_id" label={fieldLabel('Access Key ID')} rules={[{ required: true, message: 'Required' }]}>
            <Input prefix={<ApiOutlined style={{ color: '#656B75' }} />} placeholder="AKIAIOSFODNN7EXAMPLE" style={{ height: 44, ...mono }} />
          </Form.Item>
          <Form.Item name="secret_access_key" label={fieldLabel('Secret Access Key')}
            rules={editingSecret ? [] : [{ required: true, message: 'Required' }]}
            extra={editingSecret ? 'A secret is already stored. Leave empty to keep it.' : undefined}>
            <Input.Password prefix={<LockOutlined style={{ color: '#656B75' }} />} placeholder={editingSecret ? '••••••••••••••••' : 'Enter secret key'} style={{ height: 44, ...mono }} />
          </Form.Item>
          <Form.Item name="region" label={fieldLabel('Region')} initialValue="us-east-1">
            <Input placeholder="us-east-1" style={{ height: 44, ...mono }} />
          </Form.Item>
          {showEndpoint && (
            <Form.Item name="endpoint_url" label={fieldLabel('Endpoint URL')} rules={[{ required: true, message: 'Endpoint is required for non-AWS providers' }]}>
              <Input placeholder="http://minio:9000" style={{ height: 44, ...mono }} />
            </Form.Item>
          )}
          <Form.Item name="presigned_base" label={fieldLabel('Presigned URL Base (optional)')} extra="External URL the browser uses to reach storage for uploads.">
            <Input placeholder="https://minio.example.com" style={{ height: 44, ...mono }} />
          </Form.Item>

          <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '4px 0 22px' }}>
            <SafetyOutlined style={{ color: '#656B75' }} />
            <span style={{ color: '#9AA0AA', fontSize: 14, flex: 1 }}>Use SSL / HTTPS</span>
            <Switch checked={useSsl} onChange={setUseSsl} />
          </div>

          <div style={{ display: 'flex', gap: 10 }}>
            <Button style={{ flex: 1 }} onClick={handleTest} loading={testing}>Test</Button>
            <Button style={{ flex: 1 }} type="primary" htmlType="submit" loading={saving}>{editing ? 'Save' : 'Add'}</Button>
          </div>
        </Form>
      </Drawer>
    </>
  )
}

/* ── Auth method row ─────────────────────────────────────────────────────── */
function MethodRow(opts: {
  icon: React.ReactNode; name: string; desc: string; enabled: boolean
  onToggle?: (v: boolean) => void; badge?: React.ReactNode; onConfigure?: () => void; loading?: boolean
}) {
  return (
    <div style={{ background: '#121215', border: '1px solid #282C33', borderRadius: 8, padding: '18px 20px', boxShadow: '0 10px 28px rgba(0,0,0,0.14)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        <div style={{ width: 44, height: 44, borderRadius: 8, background: opts.enabled ? 'rgba(16,185,129,0.1)' : '#0C0D10', border: `1px solid ${opts.enabled ? 'rgba(16,185,129,0.24)' : '#282C33'}`, display: 'flex', alignItems: 'center', justifyContent: 'center', color: opts.enabled ? '#34D399' : '#9AA0AA', fontSize: 18, flexShrink: 0 }}>{opts.icon}</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ color: '#ECEEF1', fontWeight: 600 }}>{opts.name}</span>
            {opts.badge}
          </div>
          <div style={{ color: '#9AA0AA', fontSize: 13 }}>{opts.desc}</div>
        </div>
        {opts.onConfigure && <Button className="settings-configure" type="primary" ghost size="small" icon={<EditOutlined />} onClick={opts.onConfigure}>Configure</Button>}
        {opts.onToggle && <Switch checked={opts.enabled} onChange={opts.onToggle} loading={opts.loading} />}
      </div>
    </div>
  )
}

/* ── Auth methods section ────────────────────────────────────────────────── */
const PROVIDER_FIELDS: Record<string, { key: string; label: string; textarea?: boolean }[]> = {
  github: [{ key: 'client_id', label: 'Client ID' }, { key: 'callback_url', label: 'Callback URL' }],
  saml: [{ key: 'entity_id', label: 'Entity ID' }, { key: 'sso_url', label: 'SSO URL' }, { key: 'certificate', label: 'Certificate', textarea: true }],
}

function AuthMethods() {
  const [localEnabled, setLocalEnabled] = useState(true)
  const [entraEnabled, setEntraEnabled] = useState(false)
  const [azure, setAzure] = useState<AzureAdConfig | null>(null)
  const [providers, setProviders] = useState<AuthProvider[]>([])
  const [savingAuth, setSavingAuth] = useState(false)
  // drawer: { kind: 'azure' | providerId }
  const [drawer, setDrawer] = useState<string | null>(null)
  const [azureForm] = Form.useForm()
  const [provForm] = Form.useForm()

  const load = () => {
    settingsApi.getAuthSettings().then((r) => { setLocalEnabled(r.data.enable_local_auth); setEntraEnabled(r.data.enable_azure_ad) })
    settingsApi.getAzureSettings().then((r) => setAzure(r.data))
    settingsApi.getAuthProviders().then((r) => setProviders(r.data)).catch(() => {})
  }
  useEffect(() => { load() }, [])

  const saveToggles = async (local: boolean, entra: boolean) => {
    if (!local && !entra && !providers.some((p) => p.enabled)) { message.warning('At least one method must be enabled'); return }
    setSavingAuth(true)
    try { await settingsApi.updateAuthSettings({ enable_local_auth: local, enable_azure_ad: entra }); setLocalEnabled(local); setEntraEnabled(entra) }
    catch (e: any) { message.error(e.response?.data?.detail || 'Failed'); load() }
    finally { setSavingAuth(false) }
  }

  const openAzure = () => {
    azureForm.setFieldsValue({ tenant_id: azure?.tenant_id, client_id: azure?.client_id, redirect_uri: azure?.redirect_uri, client_secret: '' })
    setDrawer('azure')
  }
  const saveAzure = async (values: any) => {
    try {
      const payload: any = { tenant_id: values.tenant_id, client_id: values.client_id, redirect_uri: values.redirect_uri }
      if (values.client_secret) payload.client_secret = values.client_secret
      const res = await settingsApi.updateAzureSettings(payload)
      setAzure(res.data); setDrawer(null); message.success('Microsoft Entra saved')
    } catch (e: any) { message.error(e.response?.data?.detail || 'Failed') }
  }

  const openProvider = (p: AuthProvider) => { provForm.setFieldsValue({ ...p.config, secret: '' }); setDrawer(p.id) }
  const saveProvider = async (p: AuthProvider, values: any) => {
    const fields = PROVIDER_FIELDS[p.id] || []
    const config: Record<string, string> = {}
    for (const f of fields) if (values[f.key]) config[f.key] = values[f.key]
    try {
      await settingsApi.updateAuthProvider(p.id, { enabled: p.enabled, config, secret: values.secret || undefined })
      message.success(`${p.name} saved`); setDrawer(null); load()
    } catch (e: any) { message.error(e.response?.data?.detail || 'Failed') }
  }
  const toggleProvider = async (p: AuthProvider, v: boolean) => {
    try { await settingsApi.updateAuthProvider(p.id, { enabled: v, config: p.config, secret: undefined }); load() }
    catch { message.error('Failed') }
  }

  const activeProvider = providers.find((p) => p.id === drawer)

  return (
    <section>
      <SectionTitle icon={<SafetyOutlined />} title="Authentication methods" subtitle="Control how users access this s3BEAR instance." />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12, paddingTop: 18 }}>
        <MethodRow icon={<MailOutlined />} name="Local Authentication" desc="Email + password sign-in"
          enabled={localEnabled} onToggle={(v) => saveToggles(v, entraEnabled)} loading={savingAuth} />

        <MethodRow icon={<WindowsFilled />} name="Microsoft Entra" desc="Microsoft Entra ID (OAuth2 / OIDC)"
          enabled={entraEnabled} onToggle={(v) => saveToggles(localEnabled, v)} loading={savingAuth}
          onConfigure={openAzure}
          badge={azure?.has_secret && azure?.client_id ? <Tag color="success" style={{ borderRadius: 6, margin: 0 }}>Configured</Tag> : <Tag style={{ borderRadius: 6, margin: 0 }}>Not configured</Tag>} />

        {providers.map((p) => (
          <MethodRow key={p.id} icon={p.id === 'github' ? <ApiOutlined /> : <SafetyOutlined />}
            name={p.name} desc={p.type === 'saml' ? 'SAML 2.0 single sign-on' : 'OAuth2 sign-in'}
            enabled={p.enabled} onToggle={(v) => toggleProvider(p, v)} onConfigure={() => openProvider(p)}
            badge={<Tag color={p.configured ? 'success' : 'default'} style={{ borderRadius: 6, margin: 0 }}>{p.configured ? 'Configured' : 'Not configured'}</Tag>} />
        ))}
      </div>

      {/* Azure drawer */}
      <Drawer title="Configure Microsoft Entra" open={drawer === 'azure'} onClose={() => setDrawer(null)} width={460} destroyOnClose>
        <Form form={azureForm} layout="vertical" onFinish={saveAzure} requiredMark={false}>
          <Form.Item name="tenant_id" label={fieldLabel('Tenant ID')} rules={[{ required: true }]}><Input style={mono} /></Form.Item>
          <Form.Item name="client_id" label={fieldLabel('Client ID')} rules={[{ required: true }]}><Input style={mono} /></Form.Item>
          <Form.Item name="client_secret" label={fieldLabel('Client Secret')} extra={azure?.has_secret ? 'Leave empty to keep existing.' : undefined}>
            <Input.Password placeholder={azure?.has_secret ? '••••••••' : 'Enter secret'} style={mono} />
          </Form.Item>
          <Form.Item name="redirect_uri" label={fieldLabel('Redirect URI')} rules={[{ required: true }]}><Input style={mono} /></Form.Item>
          <div style={{ display: 'flex', gap: 10 }}>
            <Button style={{ flex: 1 }} onClick={() => setDrawer(null)}>Cancel</Button>
            <Button style={{ flex: 1 }} type="primary" htmlType="submit">Save</Button>
          </div>
        </Form>
      </Drawer>

      {/* Provider drawer */}
      <Drawer title={activeProvider ? `Configure ${activeProvider.name}` : ''} open={!!activeProvider} onClose={() => setDrawer(null)} width={460} destroyOnClose>
        {activeProvider && (
          <Form form={provForm} layout="vertical" onFinish={(v) => saveProvider(activeProvider, v)} requiredMark={false}>
            {(PROVIDER_FIELDS[activeProvider.id] || []).map((f) => (
              <Form.Item key={f.key} name={f.key} label={fieldLabel(f.label)}>
                {f.textarea ? <Input.TextArea rows={4} style={mono} /> : <Input style={mono} />}
              </Form.Item>
            ))}
            <Form.Item name="secret" label={fieldLabel(activeProvider.type === 'saml' ? 'Private Key (optional)' : 'Client Secret')} extra={activeProvider.has_secret ? 'Leave empty to keep existing.' : undefined}>
              <Input.Password placeholder={activeProvider.has_secret ? '••••••••' : 'Enter secret'} style={mono} />
            </Form.Item>
            <div style={{ color: '#656B75', fontSize: 12, marginBottom: 16 }}>Note: config is stored; the login flow for this provider is not wired yet.</div>
            <div style={{ display: 'flex', gap: 10 }}>
              <Button style={{ flex: 1 }} onClick={() => setDrawer(null)}>Cancel</Button>
              <Button style={{ flex: 1 }} type="primary" htmlType="submit">Save</Button>
            </div>
          </Form>
        )}
      </Drawer>
    </section>
  )
}

/* ── Page ────────────────────────────────────────────────────────────────── */
export default function SettingsPage() {
  const [tab, setTab] = useState<string | number>('storage')
  return (
    <div style={{ width: '100%', maxWidth: 1120, margin: '0 auto' }}>
      <PageHeader title="Settings" subtitle="Manage storage connections and authentication." />

      <Tabs
        activeKey={String(tab)}
        onChange={setTab}
        tabBarStyle={{ marginBottom: 28, borderBottomColor: '#282C33' }}
        items={[
          { key: 'storage', label: <Space size={8}><CloudServerOutlined />Storage</Space>, children: <StorageProviders /> },
          { key: 'auth', label: <Space size={8}><SafetyOutlined />Authentication</Space>, children: <AuthMethods /> },
        ]}
      />
    </div>
  )
}
