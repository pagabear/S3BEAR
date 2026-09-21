import { useEffect, useState } from 'react'
import {
  Button,
  Checkbox,
  Drawer,
  Form,
  Input,
  List,
  message,
  Select,
  Space,
  Spin,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd'
import { DeleteOutlined, EditOutlined, PlusOutlined, SearchOutlined } from '@ant-design/icons'
import { usersApi, groupsApi, UserRead, UserCreate, UserUpdate, EntraUser, GroupRead } from '../../api/admin'
import { settingsApi, AuthSettings } from '../../api/settings'
import { C, mono, PageHeader, EditDrawer, RowActions } from '../../components/ui'
import dayjs from 'dayjs'

type CreateMode = 'entra' | 'service'

export default function UsersPage() {
  const [users, setUsers] = useState<UserRead[]>([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [editUser, setEditUser] = useState<UserRead | null>(null)
  const [form] = Form.useForm()

  const [authConfig, setAuthConfig] = useState<AuthSettings | null>(null)
  const [groups, setGroups] = useState<GroupRead[]>([])

  // Create modal state
  const [createMode, setCreateMode] = useState<CreateMode>('entra')
  const [createModalOpen, setCreateModalOpen] = useState(false)
  const [selectedGroupIds, setSelectedGroupIds] = useState<string[]>([])

  // Entra search state
  const [entraQuery, setEntraQuery] = useState('')
  const [entraResults, setEntraResults] = useState<EntraUser[]>([])
  const [entraSearching, setEntraSearching] = useState(false)
  const [selectedEntraUsers, setSelectedEntraUsers] = useState<Set<string>>(new Set())
  const [importing, setImporting] = useState(false)

  // Service account form
  const [serviceForm] = Form.useForm()

  const load = () => {
    setLoading(true)
    usersApi.list().then((r) => { setUsers(r.data); setLoading(false) })
  }

  useEffect(() => {
    load()
    settingsApi.getAuthSettings().then((r) => setAuthConfig(r.data)).catch(() => {})
    groupsApi.list().then((r) => setGroups(r.data)).catch(() => {})
  }, [])

  const entraActive = authConfig?.enable_azure_ad ?? false

  const openCreate = () => {
    setCreateMode(entraActive ? 'entra' : 'service')
    setCreateModalOpen(true)
    setEntraQuery('')
    setEntraResults([])
    setSelectedEntraUsers(new Set())
    setSelectedGroupIds([])
    serviceForm.resetFields()
  }

  const openEdit = (u: UserRead) => {
    setEditUser(u)
    form.setFieldsValue(u)
    setModalOpen(true)
  }

  const handleEntraSearch = async () => {
    if (entraQuery.length < 2) return
    setEntraSearching(true)
    try {
      const res = await usersApi.searchEntra(entraQuery)
      setEntraResults(res.data)
      setSelectedEntraUsers(new Set())
    } catch (e: any) {
      message.error(e.response?.data?.detail || 'Entra search failed')
    } finally {
      setEntraSearching(false)
    }
  }

  const toggleEntraUser = (id: string) => {
    setSelectedEntraUsers((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleImportSelected = async () => {
    const selected = entraResults.filter((u) => selectedEntraUsers.has(u.id))
    if (selected.length === 0) { message.warning('Select at least one user'); return }
    setImporting(true)
    try {
      const res = await usersApi.importEntra(selected, selectedGroupIds)
      message.success(`Imported ${res.data.length} user(s)`)
      setCreateModalOpen(false)
      load()
    } catch (e: any) {
      message.error(e.response?.data?.detail || 'Import failed')
    } finally {
      setImporting(false)
    }
  }

  const handleCreateService = async (values: any) => {
    try {
      await usersApi.create({
        email: values.email,
        display_name: values.display_name || '',
        password: values.password,
        group_ids: selectedGroupIds,
      } as UserCreate)
      message.success('Service account created')
      setCreateModalOpen(false)
      load()
    } catch (e: any) {
      message.error(e.response?.data?.detail || 'Error')
    }
  }

  const handleEditSubmit = async (values: any) => {
    if (!editUser) return
    try {
      await usersApi.update(editUser.id, values as UserUpdate)
      message.success('User updated')
      setModalOpen(false)
      load()
    } catch (e: any) {
      message.error(e.response?.data?.detail || 'Error')
    }
  }

  const handleDelete = async (id: string) => {
    await usersApi.delete(id)
    message.success('Deleted')
    load()
  }

  const columns = [
    { title: 'Email', dataIndex: 'email', key: 'email' },
    { title: 'Display Name', dataIndex: 'display_name', key: 'display_name' },
    {
      title: 'Groups',
      key: 'groups',
      render: (_: any, r: UserRead) => (
        <Space size={4} wrap>
          {r.is_admin && <Tag color="red">Admin</Tag>}
          {r.groups.map((g) => <Tag key={g.id}>{g.name}</Tag>)}
        </Space>
      ),
    },
    {
      title: 'Status',
      key: 'status',
      width: 90,
      render: (_: any, r: UserRead) => (
        <Tag color={r.is_active ? 'green' : 'default'}>{r.is_active ? 'Active' : 'Inactive'}</Tag>
      ),
    },
    { title: 'Created', dataIndex: 'created_at', width: 120, render: (v: string) => dayjs(v).format('YYYY-MM-DD') },
    {
      title: '',
      key: 'actions',
      width: 56,
      render: (_: any, r: UserRead) => (
        <RowActions actions={[
          { key: 'edit', label: 'Edit', icon: <EditOutlined />, onClick: () => openEdit(r) },
          { key: 'delete', label: 'Delete', icon: <DeleteOutlined />, danger: true, confirm: `Delete '${r.display_name || r.email}'?`, onClick: () => handleDelete(r.id) },
        ]} />
      ),
    },
  ]

  const groupSelector = (
    <div style={{ marginBottom: 16 }}>
      <Typography.Text style={{ fontSize: 12, color: '#9AA0AA', fontFamily: "'Fira Code', monospace" }}>
        assign to groups
      </Typography.Text>
      <Select
        mode="multiple"
        placeholder="Select groups..."
        style={{ width: '100%', marginTop: 4 }}
        value={selectedGroupIds}
        onChange={setSelectedGroupIds}
        options={groups.map((g) => ({ label: g.name, value: g.id }))}
      />
    </div>
  )

  return (
    <div>
      <PageHeader
        title="Users"
        subtitle={`${users.length} user${users.length !== 1 ? 's' : ''}`}
        actions={<Button icon={<PlusOutlined />} type="primary" onClick={openCreate} style={{ fontWeight: 600, height: 40 }}>Add User</Button>}
      />
      <Table rowKey="id" columns={columns} dataSource={users} loading={loading} />

      {/* Edit drawer — delete lives inside */}
      <EditDrawer
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title={editUser ? `Edit ${editUser.display_name || editUser.email}` : 'Edit User'}
        onSubmit={() => form.submit()}
        onDelete={editUser ? () => { handleDelete(editUser.id); setModalOpen(false) } : undefined}
        deleteLabel="Delete user"
        deleteConfirm="This permanently removes the user."
      >
        {editUser && (
          <div style={{ ...mono, fontSize: 12, color: C.dim, marginBottom: 16 }}>{editUser.email}</div>
        )}
        <Form form={form} layout="vertical" onFinish={handleEditSubmit}>
          <Form.Item name="display_name" label="Display Name">
            <Input />
          </Form.Item>
          <Form.Item name="is_active" label="Active" valuePropName="checked">
            <Switch defaultChecked />
          </Form.Item>
          <Form.Item name="is_admin" label="Admin" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item
            name="password"
            label="Password"
            extra="Leave empty to keep existing password"
          >
            <Input.Password placeholder="Leave empty to keep unchanged" />
          </Form.Item>
        </Form>
      </EditDrawer>

      {/* Create / Import drawer */}
      <Drawer
        open={createModalOpen}
        title="New User"
        onClose={() => setCreateModalOpen(false)}
        width={560}
        destroyOnClose
      >
        {/* Mode toggle */}
        {entraActive && (
          <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
            <Button
              type={createMode === 'entra' ? 'primary' : 'default'}
              onClick={() => setCreateMode('entra')}
              style={{ flex: 1, fontFamily: "'Fira Code', monospace", fontSize: 12 }}
            >
              import from entra
            </Button>
            <Button
              type={createMode === 'service' ? 'primary' : 'default'}
              onClick={() => setCreateMode('service')}
              style={{ flex: 1, fontFamily: "'Fira Code', monospace", fontSize: 12 }}
            >
              service account
            </Button>
          </div>
        )}

        {createMode === 'entra' && entraActive ? (
          <>
            <Space.Compact style={{ width: '100%', marginBottom: 12 }}>
              <Input
                placeholder="Search by name or email..."
                prefix={<SearchOutlined />}
                value={entraQuery}
                onChange={(e) => setEntraQuery(e.target.value)}
                onPressEnter={handleEntraSearch}
              />
              <Button type="primary" onClick={handleEntraSearch} loading={entraSearching}>
                Search
              </Button>
            </Space.Compact>

            {entraSearching ? (
              <div style={{ textAlign: 'center', padding: 32 }}><Spin /></div>
            ) : (
              <List
                style={{ maxHeight: 300, overflow: 'auto', marginBottom: 16 }}
                dataSource={entraResults}
                locale={{ emptyText: entraQuery ? 'No users found' : 'Search for Entra users above' }}
                renderItem={(item) => (
                  <List.Item
                    style={{ cursor: 'pointer' }}
                    onClick={() => toggleEntraUser(item.id)}
                    actions={[
                      <Checkbox key="cb" checked={selectedEntraUsers.has(item.id)} />,
                    ]}
                  >
                    <List.Item.Meta
                      title={item.displayName}
                      description={item.mail || item.userPrincipalName}
                    />
                  </List.Item>
                )}
              />
            )}

            {entraResults.length > 0 && (
              <>
                {groupSelector}
                <Button
                  type="primary"
                  block
                  loading={importing}
                  disabled={selectedEntraUsers.size === 0}
                  onClick={handleImportSelected}
                  style={{ fontFamily: "'Fira Code', monospace", fontSize: 12 }}
                >
                  import {selectedEntraUsers.size} selected user{selectedEntraUsers.size !== 1 ? 's' : ''}
                </Button>
              </>
            )}
          </>
        ) : (
          <Form form={serviceForm} layout="vertical" onFinish={handleCreateService}>
            <Form.Item name="email" label="Email" rules={[{ required: true, type: 'email' }]}>
              <Input placeholder="service@example.com" />
            </Form.Item>
            <Form.Item name="display_name" label="Display Name">
              <Input placeholder="Service Account" />
            </Form.Item>
            <Form.Item name="password" label="Password" rules={[{ required: true, message: 'Password is required for service accounts' }]}>
              <Input.Password placeholder="Set a password" />
            </Form.Item>
            {groupSelector}
            <Button
              type="primary"
              htmlType="submit"
              block
              style={{ fontFamily: "'Fira Code', monospace", fontSize: 12 }}
            >
              create service account
            </Button>
          </Form>
        )}
      </Drawer>
    </div>
  )
}
