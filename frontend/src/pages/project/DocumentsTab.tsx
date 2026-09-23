import {
  CheckCircleOutlined, DeleteOutlined, EyeOutlined, FileExcelOutlined, FileImageOutlined, FilePdfOutlined,
  FileTextOutlined, FileWordOutlined, InboxOutlined, LoadingOutlined, MoreOutlined, RedoOutlined, WarningOutlined,
} from '@ant-design/icons'
import { useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Card, Col, Dropdown, List, Row, Space, Tag, Tooltip, Typography, Upload, App as AntApp } from 'antd'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { api } from '../../api/client'
import type { DocBrief, Side } from '../../api/types'
import { canEdit, useAuth } from '../../auth/AuthContext'
import { fmtSize, sideColor, useMeta } from '../../components/common'
import { useOpenSource } from '../../components/DocumentViewer'
import { useDocuments } from '../ProjectPage'

function fileIcon(name: string) {
  const ext = name.split('.').pop()?.toLowerCase()
  if (ext === 'pdf') return <FilePdfOutlined style={{ color: '#dc2626' }} />
  if (ext === 'xlsx' || ext === 'csv' || ext === 'xlsm') return <FileExcelOutlined style={{ color: '#16a34a' }} />
  if (['png', 'jpg', 'jpeg', 'tif', 'tiff', 'bmp', 'webp'].includes(ext || '')) return <FileImageOutlined style={{ color: '#7c3aed' }} />
  if (ext === 'docx' || ext === 'doc') return <FileWordOutlined style={{ color: '#2563eb' }} />
  return <FileTextOutlined />
}

function SideColumn({ projectId, side, docs, editable }: { projectId: number; side: Side; docs: DocBrief[]; editable: boolean }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const { message, modal } = AntApp.useApp()
  const open = useOpenSource()
  const [uploading, setUploading] = useState(false)
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['documents', projectId] })
    qc.invalidateQueries({ queryKey: ['project', projectId] })
  }

  const uploadFiles = async (files: File[]) => {
    const form = new FormData()
    form.append('side', side)
    files.forEach((f) => form.append('files', f))
    setUploading(true)
    try {
      await api(`/projects/${projectId}/documents`, { form })
      refresh()
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setUploading(false)
    }
  }

  const statusTag = (d: DocBrief) => {
    if (d.status === 'parsed') return <Tag icon={<CheckCircleOutlined />} color="success">{d.clause_count} {t('documents.clauses')}</Tag>
    if (d.status === 'error') return <Tooltip title={d.error}><Tag icon={<WarningOutlined />} color="error">{t('docStatus.error')}</Tag></Tooltip>
    return <Tag icon={<LoadingOutlined />} color="processing">{t(`docStatus.${d.status}`)}</Tag>
  }

  const sides: Side[] = ['before', 'after', 'requirements', 'benchmark']
  return (
    <Card className="side-col" size="small"
      title={<Space><Tag color={sideColor(side)} style={{ marginInlineEnd: 0 }}>{docs.length}</Tag>{t(`sides.${side}`)}</Space>}
      styles={{ body: { padding: 12 } }}>
      <Typography.Paragraph type="secondary" className="small" style={{ marginBottom: 8 }}>
        {t(`sides.${side}Hint`)}
      </Typography.Paragraph>
      {editable && (
        <div className="upload-side">
          <Upload.Dragger multiple showUploadList={false} disabled={uploading}
            beforeUpload={(file, list) => {
              if (file === list[list.length - 1]) uploadFiles(list as unknown as File[])
              return false
            }}>
            <p className="ant-upload-drag-icon" style={{ marginBottom: 4 }}>
              {uploading ? <LoadingOutlined /> : <InboxOutlined />}
            </p>
            <p className="ant-upload-text" style={{ fontSize: 13 }}>{t('documents.drop')}</p>
            <p className="ant-upload-hint small">{t('documents.formats')}</p>
          </Upload.Dragger>
        </div>
      )}
      <List
        size="small"
        style={{ marginTop: 8 }}
        locale={{ emptyText: t('documents.empty') }}
        dataSource={docs}
        renderItem={(d) => (
          <List.Item
            actions={[
              <Tooltip title={t('documents.view')} key="v">
                <Button size="small" type="text" icon={<EyeOutlined />} disabled={d.status !== 'parsed'}
                  onClick={() => open({ docId: d.id })} />
              </Tooltip>,
              editable && (
                <Dropdown key="m" trigger={['click']} menu={{
                  items: [
                    { key: 'reparse', icon: <RedoOutlined />, label: t('documents.reparse'),
                      onClick: async () => { await api(`/documents/${d.id}/reparse`, { method: 'POST' }); refresh() } },
                    { key: 'move', label: t('documents.moveTo'),
                      children: sides.filter((s) => s !== d.side).map((s) => ({
                        key: s, label: t(`sides.${s}`),
                        onClick: async () => { await api(`/documents/${d.id}`, { method: 'PATCH', body: { side: s } }); refresh() },
                      })) },
                    { type: 'divider' },
                    { key: 'del', icon: <DeleteOutlined />, danger: true, label: t('common.delete'),
                      onClick: () => modal.confirm({
                        title: t('common.confirmDelete'), content: d.filename, okButtonProps: { danger: true },
                        onOk: async () => { await api(`/documents/${d.id}`, { method: 'DELETE' }); refresh() },
                      }) },
                  ],
                }}>
                  <Button size="small" type="text" icon={<MoreOutlined />} />
                </Dropdown>
              ),
            ].filter(Boolean)}
          >
            <List.Item.Meta
              avatar={<span style={{ fontSize: 20 }}>{fileIcon(d.filename)}</span>}
              title={<Typography.Text ellipsis={{ tooltip: d.title }} style={{ maxWidth: 260 }}>{d.title}</Typography.Text>}
              description={
                <Space size={[4, 4]} wrap>
                  {statusTag(d)}
                  {d.status === 'parsed' && <Tag bordered={false}>{t(`docKinds.${d.doc_kind}`, d.doc_kind)}</Tag>}
                  {d.edition && <Tag bordered={false}>ред. {d.edition}</Tag>}
                  {d.has_orgchart && <Tag color="purple" bordered={false}>{t('documents.orgchart')}</Tag>}
                  <span className="small muted">{t(`documents.methods.${d.method}`, d.method || '')} · {fmtSize(d.size)}</span>
                  {d.warnings?.length > 0 && <Tooltip title={d.warnings.join('; ')}><WarningOutlined style={{ color: '#d97706' }} /></Tooltip>}
                </Space>
              }
            />
          </List.Item>
        )}
      />
    </Card>
  )
}

export default function DocumentsTab({ projectId }: { projectId: number }) {
  const { t } = useTranslation()
  const { user } = useAuth()
  const nav = useNavigate()
  const meta = useMeta()
  const docs = useDocuments(projectId)
  const all = docs.data || []
  const by = (s: Side) => all.filter((d) => d.side === s)
  const parsed = (s: Side) => by(s).some((d) => d.status === 'parsed')
  const ready = parsed('before') && parsed('after')
  const editable = canEdit(user)

  return (
    <>
      {ready ? (
        <Alert type="success" showIcon message={t('documents.ready')} style={{ marginBottom: 16 }}
          action={<Button type="primary" onClick={() => nav(`/projects/${projectId}/analysis`)}>{t('documents.toAnalysis')}</Button>} />
      ) : (
        <Alert type="info" showIcon message={t('documents.needBoth')} style={{ marginBottom: 16 }}
          description={meta.data && !meta.data.ocr ? t('ai.ocrOff') : undefined} />
      )}
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}><SideColumn projectId={projectId} side="before" docs={by('before')} editable={editable} /></Col>
        <Col xs={24} lg={12}><SideColumn projectId={projectId} side="after" docs={by('after')} editable={editable} /></Col>
        <Col xs={24} lg={12}><SideColumn projectId={projectId} side="requirements" docs={by('requirements')} editable={editable} /></Col>
        <Col xs={24} lg={12}><SideColumn projectId={projectId} side="benchmark" docs={by('benchmark')} editable={editable} /></Col>
      </Row>
    </>
  )
}
