import React, { useCallback, useEffect, useState } from 'react'
import {
  Breadcrumb,
  Button,
  message,
  Popconfirm,
  Space,
  Table,
  Tooltip,
  Typography,
} from 'antd'
import {
  DeleteOutlined,
  DragOutlined,
  FileImageOutlined,
  FileOutlined,
  FolderOutlined,
  LinkOutlined,
  ScissorOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import { BrowseResult, bucketsApi, S3Object } from '../../api/buckets'
import UploadButton from '../UploadButton'
import CopyMoveModal from '../CopyMoveModal'
import ShareModal from '../ShareModal'
import dayjs from 'dayjs'

const IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp', '.avif']

function isImage(key: string) {
  return IMAGE_EXTENSIONS.some((ext) => key.toLowerCase().endsWith(ext))
}

function formatBytes(bytes: number) {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`
}

interface BucketBrowserProps {
  bucket: string
  canWrite: boolean
  canDelete: boolean
}

export default function BucketBrowser({ bucket, canWrite, canDelete }: BucketBrowserProps) {
  const [prefix, setPrefix] = useState('')
  const [data, setData] = useState<BrowseResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [selectedKeys, setSelectedKeys] = useState<string[]>([])
  const [uploadVisible, setUploadVisible] = useState(false)
  const [copyMoveModal, setCopyMoveModal] = useState<{
    visible: boolean
    mode: 'copy' | 'move'
    sourceKey?: string
    keys?: string[]
  }>({ visible: false, mode: 'copy' })
  const [shareModal, setShareModal] = useState<{ visible: boolean; key: string }>({
    visible: false,
    key: '',
  })

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await bucketsApi.browse(bucket, prefix)
      setData(res.data)
    } catch {
      message.error('Failed to load objects')
    } finally {
      setLoading(false)
    }
  }, [bucket, prefix])

  useEffect(() => {
    load()
  }, [load])

  const handleDeleteSelected = async () => {
    try {
      await bucketsApi.deleteObjects(bucket, selectedKeys)
      message.success(`Deleted ${selectedKeys.length} objects`)
      setSelectedKeys([])
      load()
    } catch {
      message.error('Delete failed')
    }
  }

  const handleBulkCopyMove = (mode: 'copy' | 'move') => {
    setCopyMoveModal({ visible: true, mode, keys: selectedKeys })
  }

  const breadcrumbParts = prefix.split('/').filter(Boolean)

  const monoStyle: React.CSSProperties = { fontFamily: "'Fira Code', monospace", fontSize: 12 }

  const columns = [
    {
      title: 'name',
      key: 'name',
      render: (_: any, record: any) => {
        if (record.isFolder) {
          return (
            <Button
              type="text"
              icon={<FolderOutlined style={{ color: '#F59E0B', fontSize: 13 }} />}
              onClick={() => setPrefix(record.key)}
              style={{ ...monoStyle, color: '#F59E0B', padding: '0 4px', fontWeight: 500 }}
            >
              {record.key.replace(prefix, '').replace(/\/$/, '')}/
            </Button>
          )
        }
        const name = record.key.replace(prefix, '')
        const isImg = isImage(record.key)
        return (
          <Space size={8}>
            {isImg
              ? <FileImageOutlined style={{ color: '#10B981', fontSize: 13 }} />
              : <FileOutlined style={{ color: '#656B75', fontSize: 13 }} />
            }
            <span style={{ ...monoStyle, color: '#CBD5E1' }}>{name}</span>
          </Space>
        )
      },
    },
    {
      title: 'size',
      dataIndex: 'size',
      key: 'size',
      width: 100,
      render: (v: number, record: any) => (
        <span style={{ ...monoStyle, color: '#656B75' }}>{record.isFolder ? '—' : formatBytes(v)}</span>
      ),
    },
    {
      title: 'modified',
      dataIndex: 'last_modified',
      key: 'last_modified',
      width: 160,
      render: (v: string, record: any) => (
        <span style={{ ...monoStyle, color: '#656B75' }}>{record.isFolder ? '—' : dayjs(v).format('YYYY-MM-DD HH:mm')}</span>
      ),
    },
    {
      title: '',
      key: 'actions',
      width: 120,
      render: (_: any, record: any) => {
        if (record.isFolder) return null
        return (
          <Space size={0}>
            <Tooltip title="share link">
              <Button
                type="text"
                size="small"
                icon={<LinkOutlined />}
                onClick={() => setShareModal({ visible: true, key: record.key })}
                style={{ color: '#656B75', opacity: 0.7 }}
              />
            </Tooltip>
            {canWrite && (
              <Tooltip title="copy to...">
                <Button
                  type="text"
                  size="small"
                  icon={<DragOutlined />}
                  onClick={() => setCopyMoveModal({ visible: true, mode: 'copy', sourceKey: record.key })}
                  style={{ color: '#656B75', opacity: 0.7 }}
                />
              </Tooltip>
            )}
            {canWrite && canDelete && (
              <Tooltip title="move to...">
                <Button
                  type="text"
                  size="small"
                  icon={<ScissorOutlined />}
                  onClick={() => setCopyMoveModal({ visible: true, mode: 'move', sourceKey: record.key })}
                  style={{ color: '#656B75', opacity: 0.7 }}
                />
              </Tooltip>
            )}
          </Space>
        )
      },
    },
  ]

  const tableData = [
    ...(data?.common_prefixes.map((p) => ({ key: p, isFolder: true, size: 0 })) || []),
    ...(data?.objects.map((o) => ({ ...o, isFolder: false })) || []),
  ]

  const rowSelection = canDelete
    ? {
        selectedRowKeys: selectedKeys,
        onChange: (keys: React.Key[]) => setSelectedKeys(keys as string[]),
        getCheckboxProps: (record: any) => ({ disabled: record.isFolder }),
      }
    : undefined

  return (
    <div>
      {/* Toolbar */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 12,
          padding: '8px 14px',
          background: '#15171B',
          borderRadius: 6,
          border: '1px solid #282C33',
          flexWrap: 'wrap',
          gap: 8,
        }}
      >
        <Breadcrumb
          separator={<span style={{ color: '#656B75', fontFamily: "'Fira Code', monospace", fontSize: 12 }}>/</span>}
          items={[
            {
              title: (
                <Button
                  type="text"
                  size="small"
                  onClick={() => setPrefix('')}
                  style={{ color: '#9AA0AA', padding: '0 4px', fontFamily: "'Fira Code', monospace", fontSize: 12 }}
                >
                  ~/{bucket}
                </Button>
              ),
            },
            ...breadcrumbParts.map((part, i) => ({
              title: (
                <Button
                  type="text"
                  size="small"
                  onClick={() => setPrefix(breadcrumbParts.slice(0, i + 1).join('/') + '/')}
                  style={{
                    color: i === breadcrumbParts.length - 1 ? '#ECEEF1' : '#9AA0AA',
                    padding: '0 4px',
                    fontFamily: "'Fira Code', monospace",
                    fontSize: 12,
                  }}
                >
                  {part}
                </Button>
              ),
            })),
          ]}
        />
        <Space size={6}>
          {canWrite && selectedKeys.length > 0 && (
            <Button
              icon={<DragOutlined />}
              size="small"
              onClick={() => handleBulkCopyMove('copy')}
              style={{ fontFamily: "'Fira Code', monospace", fontSize: 11 }}
            >
              cp ({selectedKeys.length})
            </Button>
          )}
          {canWrite && canDelete && selectedKeys.length > 0 && (
            <Button
              icon={<ScissorOutlined />}
              size="small"
              onClick={() => handleBulkCopyMove('move')}
              style={{ fontFamily: "'Fira Code', monospace", fontSize: 11 }}
            >
              mv ({selectedKeys.length})
            </Button>
          )}
          {canDelete && selectedKeys.length > 0 && (
            <Popconfirm
              title={`Delete ${selectedKeys.length} object(s)?`}
              onConfirm={handleDeleteSelected}
            >
              <Button danger icon={<DeleteOutlined />} size="small" style={{ fontFamily: "'Fira Code', monospace", fontSize: 11 }}>
                rm ({selectedKeys.length})
              </Button>
            </Popconfirm>
          )}
          {canWrite && (
            <Button
              icon={<UploadOutlined />}
              onClick={() => setUploadVisible(true)}
              size="small"
              type="primary"
              style={{ fontFamily: "'Fira Code', monospace", fontSize: 11 }}
            >
              upload
            </Button>
          )}
        </Space>
      </div>

      <Table
        rowKey="key"
        rowSelection={rowSelection}
        columns={columns}
        dataSource={tableData}
        loading={loading}
        pagination={{ pageSize: 50, size: 'small' }}
        size="small"
        style={{ background: 'transparent' }}
      />

      <UploadButton
        bucket={bucket}
        prefix={prefix}
        visible={uploadVisible}
        onClose={() => setUploadVisible(false)}
        onSuccess={() => {
          setUploadVisible(false)
          load()
        }}
      />

      <CopyMoveModal
        visible={copyMoveModal.visible}
        mode={copyMoveModal.mode}
        sourceBucket={bucket}
        sourceKey={copyMoveModal.sourceKey}
        keys={copyMoveModal.keys}
        onClose={() => setCopyMoveModal((prev) => ({ ...prev, visible: false }))}
        onSuccess={() => {
          setCopyMoveModal((prev) => ({ ...prev, visible: false }))
          setSelectedKeys([])
          load()
        }}
      />

      <ShareModal
        bucket={bucket}
        objectKey={shareModal.key}
        visible={shareModal.visible}
        onClose={() => setShareModal({ visible: false, key: '' })}
      />
    </div>
  )
}
