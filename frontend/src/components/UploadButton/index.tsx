import React, { useRef, useState } from 'react'
import { InboxOutlined } from '@ant-design/icons'
import { Button, message, Modal, Progress, Space, Upload } from 'antd'
import { bucketsApi } from '../../api/buckets'
import { multipartUpload, MultipartUploadHandle, UploadProgress } from '../../utils/multipartUpload'

const { Dragger } = Upload

const MULTIPART_THRESHOLD = 100 * 1024 * 1024 // 100 MB

interface UploadButtonProps {
  bucket: string
  prefix: string
  onSuccess: () => void
  visible: boolean
  onClose: () => void
}

export default function UploadButton({ bucket, prefix, onSuccess, visible, onClose }: UploadButtonProps) {
  const [uploading, setUploading] = useState(false)
  const [multipartProgress, setMultipartProgress] = useState<UploadProgress | null>(null)
  const handleRef = useRef<MultipartUploadHandle | null>(null)

  const customRequest = async ({ file, onSuccess: done, onError, onProgress }: any) => {
    const f = file as File
    setUploading(true)

    if (f.size >= MULTIPART_THRESHOLD) {
      // Multipart upload via presigned URLs
      try {
        setMultipartProgress({ loaded: 0, total: f.size, percentage: 0 })
        const handle = multipartUpload(bucket, f, prefix, (progress) => {
          setMultipartProgress(progress)
          onProgress?.({ percent: progress.percentage })
        })
        handleRef.current = handle
        await handle.promise
        handleRef.current = null
        setMultipartProgress(null)
        message.success(`${f.name} uploaded (multipart)`)
        done?.()
        onSuccess()
      } catch (err: any) {
        setMultipartProgress(null)
        handleRef.current = null
        if (err.message !== 'Upload aborted') {
          message.error(`Upload failed: ${err?.response?.data?.detail || err.message}`)
        }
        onError?.(err)
      } finally {
        setUploading(false)
      }
    } else {
      // Simple upload
      try {
        await bucketsApi.upload(bucket, f, prefix)
        message.success(`${f.name} uploaded`)
        done?.()
        onSuccess()
      } catch (err: any) {
        message.error(`Upload failed: ${err?.response?.data?.detail || err.message}`)
        onError?.(err)
      } finally {
        setUploading(false)
      }
    }
  }

  const handleAbort = () => {
    if (handleRef.current) {
      handleRef.current.abort()
      handleRef.current = null
      setMultipartProgress(null)
      setUploading(false)
      message.info('Upload cancelled')
    }
  }

  return (
    <Modal
      open={visible}
      onCancel={() => {
        if (uploading) handleAbort()
        onClose()
      }}
      footer={null}
      title={
        <span style={{ fontFamily: "'Fira Code', monospace", fontSize: 13, color: '#ECEEF1' }}>
          upload
        </span>
      }
    >
      <Dragger multiple customRequest={customRequest} showUploadList>
        <p className="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <p className="ant-upload-text" style={{ fontFamily: "'Fira Code', monospace", fontSize: 12 }}>
          click or drag files to upload
        </p>
        <p className="ant-upload-hint" style={{ fontFamily: "'Fira Code', monospace", fontSize: 11, color: '#9AA0AA' }}>
          {bucket}/{prefix || '(root)'} &middot; files &gt;100MB use multipart
        </p>
      </Dragger>

      {multipartProgress && (
        <div style={{ marginTop: 16 }}>
          <Progress
            percent={multipartProgress.percentage}
            size="small"
            strokeColor="#10B981"
            trailColor="#282C33"
          />
          <Space style={{ marginTop: 8 }}>
            <span style={{ fontFamily: "'Fira Code', monospace", fontSize: 11, color: '#9AA0AA' }}>
              {formatBytes(multipartProgress.loaded)} / {formatBytes(multipartProgress.total)}
            </span>
            <Button size="small" danger onClick={handleAbort} style={{ fontFamily: "'Fira Code', monospace", fontSize: 11 }}>
              cancel
            </Button>
          </Space>
        </div>
      )}
    </Modal>
  )
}

function formatBytes(bytes: number) {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`
}
