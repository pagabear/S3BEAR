import React, { useEffect, useState } from 'react'
import { Alert, Button, Input, message, Modal, Select, Space, Typography } from 'antd'
import { CopyOutlined, LinkOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { shareApi } from '../../api/share'

interface ShareModalProps {
  bucket: string
  objectKey: string
  visible: boolean
  onClose: () => void
}

const EXPIRY_OPTIONS = [
  { label: '1 hour', value: '1h' },
  { label: '24 hours', value: '24h' },
  { label: '7 days', value: '7d' },
  { label: '30 days', value: '30d' },
  { label: 'Never (permanent)', value: 'never' },
]

export default function ShareModal({ bucket, objectKey, visible, onClose }: ShareModalProps) {
  const [shareUrl, setShareUrl] = useState<string | null>(null)
  const [expiresAt, setExpiresAt] = useState<string | null>(null)
  const [expiresIn, setExpiresIn] = useState<string>('7d')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!visible) {
      setShareUrl(null)
      setExpiresAt(null)
      setExpiresIn('7d')
    }
  }, [visible])

  const handleCreateLink = async () => {
    setLoading(true)
    try {
      const res = await shareApi.create(bucket, objectKey, expiresIn)
      setShareUrl(`${window.location.origin}${res.data.url}`)
      setExpiresAt(res.data.expires_at)
    } catch {
      message.error('Failed to create share link')
    } finally {
      setLoading(false)
    }
  }

  const handleCopy = async () => {
    if (!shareUrl) return
    try {
      await navigator.clipboard.writeText(shareUrl)
      message.success('Link copied to clipboard')
    } catch {
      message.error('Failed to copy')
    }
  }

  return (
    <Modal
      open={visible}
      onCancel={onClose}
      footer={null}
      title={`Share: ${objectKey.split('/').pop()}`}
      width={600}
      centered
    >
      <div style={{ padding: '16px 0' }}>
        {!shareUrl ? (
          <Space direction="vertical" style={{ width: '100%' }} size={16}>
            <div>
              <div style={{ marginBottom: 6, color: '#9AA0AA', fontSize: 12, fontFamily: "'Fira Code', monospace" }}>
                Link expires after
              </div>
              <Select
                value={expiresIn}
                onChange={setExpiresIn}
                options={EXPIRY_OPTIONS}
                style={{ width: '100%' }}
              />
            </div>
            {expiresIn === 'never' && (
              <Alert
                type="warning"
                showIcon
                message="Permanent link"
                description="This link never expires. Anyone with the URL can access the object until you revoke it from the Shares page."
              />
            )}
            <Button
              icon={<LinkOutlined />}
              onClick={handleCreateLink}
              loading={loading}
              type="primary"
              block
            >
              Generate Share Link
            </Button>
          </Space>
        ) : (
          <Space direction="vertical" style={{ width: '100%' }} size={12}>
            <Space.Compact style={{ width: '100%' }}>
              <Input value={shareUrl} readOnly />
              <Button icon={<CopyOutlined />} onClick={handleCopy}>
                Copy
              </Button>
            </Space.Compact>
            <Typography.Text type="secondary" style={{ fontFamily: "'Fira Code', monospace", fontSize: 12 }}>
              {expiresAt
                ? `Expires ${dayjs(expiresAt).format('YYYY-MM-DD HH:mm')}`
                : 'Never expires — revoke from the Shares page when done'}
            </Typography.Text>
          </Space>
        )}
      </div>
    </Modal>
  )
}
