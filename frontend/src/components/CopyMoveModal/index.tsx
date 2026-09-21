import React, { useEffect, useState } from 'react'
import { Input, message, Modal, Select, Space, Typography } from 'antd'
import { BucketInfo, bucketsApi } from '../../api/buckets'

interface CopyMoveModalProps {
  visible: boolean
  mode: 'copy' | 'move'
  sourceBucket: string
  sourceKey?: string // single-object mode
  keys?: string[] // bulk mode (takes precedence when non-empty)
  onClose: () => void
  onSuccess: () => void
}

const mono = { fontFamily: "'Fira Code', monospace" }

export default function CopyMoveModal({
  visible,
  mode,
  sourceBucket,
  sourceKey = '',
  keys,
  onClose,
  onSuccess,
}: CopyMoveModalProps) {
  const bulk = !!keys && keys.length > 0
  const [buckets, setBuckets] = useState<BucketInfo[]>([])
  const [destBucket, setDestBucket] = useState(sourceBucket)
  const [destKey, setDestKey] = useState(sourceKey)
  const [destPrefix, setDestPrefix] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (visible) {
      setDestBucket(sourceBucket)
      setDestKey(sourceKey)
      setDestPrefix('')
      bucketsApi.list().then((res) => setBuckets(res.data)).catch(() => {})
    }
  }, [visible, sourceBucket, sourceKey])

  const handleOk = async () => {
    setLoading(true)
    try {
      if (bulk) {
        const res =
          mode === 'copy'
            ? await bucketsApi.bulkCopy(destBucket, sourceBucket, keys!, destPrefix)
            : await bucketsApi.bulkMove(destBucket, sourceBucket, keys!, destPrefix)
        const { succeeded, errors } = res.data
        if (errors.length === 0) {
          message.success(`${mode === 'copy' ? 'Copied' : 'Moved'} ${succeeded.length} object(s)`)
        } else {
          message.warning(`${succeeded.length} succeeded, ${errors.length} failed`)
        }
        onSuccess()
      } else {
        if (!destKey.trim()) {
          message.error('Destination key is required')
          setLoading(false)
          return
        }
        if (mode === 'copy') {
          await bucketsApi.copyObject(destBucket, sourceBucket, sourceKey, destKey)
          message.success('Object copied')
        } else {
          await bucketsApi.moveObject(destBucket, sourceBucket, sourceKey, destKey)
          message.success('Object moved')
        }
        onSuccess()
      }
    } catch (err: any) {
      message.error(err?.response?.data?.detail || `${mode} failed`)
    } finally {
      setLoading(false)
    }
  }

  const title = bulk
    ? `${mode === 'copy' ? 'cp' : 'mv'} ${keys!.length} objects`
    : `${mode === 'copy' ? 'cp' : 'mv'} ${sourceKey.split('/').pop()}`

  return (
    <Modal
      open={visible}
      title={<span style={{ ...mono, fontSize: 13, color: '#ECEEF1' }}>{title}</span>}
      onCancel={onClose}
      onOk={handleOk}
      confirmLoading={loading}
      okText={mode}
      width={480}
    >
      <Space direction="vertical" style={{ width: '100%', marginTop: 12 }} size={12}>
        <div>
          <div style={{ color: '#9AA0AA', fontSize: 11, ...mono, marginBottom: 4 }}>destination bucket</div>
          <Select
            value={destBucket}
            onChange={setDestBucket}
            style={{ width: '100%' }}
            options={buckets.filter((b) => b.can_write).map((b) => ({ label: b.name, value: b.name }))}
          />
        </div>
        {bulk ? (
          <div>
            <div style={{ color: '#9AA0AA', fontSize: 11, ...mono, marginBottom: 4 }}>
              destination prefix (optional)
            </div>
            <Input
              value={destPrefix}
              onChange={(e) => setDestPrefix(e.target.value)}
              placeholder="e.g. archive/2026/"
              style={{ ...mono, fontSize: 12 }}
            />
            <Typography.Text type="secondary" style={{ ...mono, fontSize: 11 }}>
              Each object keeps its filename under this prefix.
            </Typography.Text>
          </div>
        ) : (
          <div>
            <div style={{ color: '#9AA0AA', fontSize: 11, ...mono, marginBottom: 4 }}>destination key</div>
            <Input value={destKey} onChange={(e) => setDestKey(e.target.value)} style={{ ...mono, fontSize: 12 }} />
          </div>
        )}
      </Space>
    </Modal>
  )
}
