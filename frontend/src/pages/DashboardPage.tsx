import {
  CloudUploadOutlined, DeleteOutlined, DownOutlined, ExperimentOutlined, FileDoneOutlined, FolderAddOutlined,
  PlusOutlined, SearchOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Badge, Button, Card, Col, Dropdown, Empty, Form, Input, Modal, Popconfirm, Progress, Row, Space, Steps, Tag, Tooltip,
  Typography, App as AntApp,
} from 'antd'
import dayjs from 'dayjs'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { Project } from '../api/types'
import { canEdit, useAuth } from '../auth/AuthContext'
import { UnitStatusTag, useMeta } from '../components/common'

export function NewProjectModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const [form] = Form.useForm()
  const nav = useNavigate()
  const qc = useQueryClient()
  const { message } = AntApp.useApp()
  const create = useMutation({
    mutationFn: (v: { name: string; description?: string }) => api<Project>('/projects', { body: v }),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ['projects'] })
      form.resetFields()
      onClose()
      nav(`/projects/${p.id}/documents`)
    },
    onError: (e: Error) => message.error(e.message),
  })
  return (
    <Modal open={open} title={t('dashboard.newTitle')} onCancel={onClose} confirmLoading={create.isPending}
      onOk={() => form.validateFields().then((v) => create.mutate(v))} okText={t('common.add')}>
      <Form form={form} layout="vertical">
        <Form.Item name="name" label={t('common.name')} rules={[{ required: true }]}>
          <Input placeholder={t('dashboard.namePh')} autoFocus />
        </Form.Item>
        <Form.Item name="description" label={t('common.description')}>
          <Input.TextArea rows={3} placeholder={t('dashboard.descPh')} />
        </Form.Item>
      </Form>
    </Modal>
  )
}

function ProjectCard({ p }: { p: Project }) {
  const { t } = useTranslation()
  const nav = useNavigate()
  const qc = useQueryClient()
  const { message } = AntApp.useApp()
  const run = p.last_run
  const del = useMutation({
    mutationFn: () => api(`/projects/${p.id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['projects'] }),
    onError: (e: Error) => message.error(e.message),
  })
  return (
    <Card hoverable onClick={() => nav(`/projects/${p.id}`)} style={{ height: '100%' }}
      title={<Space>{p.is_demo && <Tag color="purple">DEMO</Tag>}<span>{p.name}</span></Space>}
      extra={p.can_delete && (
        <Popconfirm title={t('project.deleteConfirm')} onConfirm={(e) => { e?.stopPropagation(); del.mutate() }}
          onCancel={(e) => e?.stopPropagation()}>
          <Button type="text" size="small" danger icon={<DeleteOutlined />} onClick={(e) => e.stopPropagation()} />
        </Popconfirm>
      )}>
      <Typography.Paragraph type="secondary" className="clamp-2" style={{ minHeight: 44 }}>
        {p.description || '—'}
      </Typography.Paragraph>
      <Space wrap size={[4, 4]} style={{ marginBottom: 12 }}>
        <Tag color="orange">{t('sides.short.before')}: {p.documents.before}</Tag>
        <Tag color="green">{t('sides.short.after')}: {p.documents.after}</Tag>
        {p.documents.requirements > 0 && <Tag color="purple">{t('sides.short.requirements')}: {p.documents.requirements}</Tag>}
        {p.documents.benchmark > 0 && <Tag color="cyan">{t('sides.short.benchmark')}: {p.documents.benchmark}</Tag>}
      </Space>
      {run ? (
        run.status === 'done' ? (
          <div>
            <Space size={16} wrap>
              <Tooltip title={t('analysis.cards.lost')}><Badge color="red" text={`${run.lost ?? 0}`} /></Tooltip>
              <Tooltip title={t('analysis.cards.dups')}><Badge color="orange" text={`${run.duplicates ?? 0}`} /></Tooltip>
              <Tooltip title={t('analysis.cards.conflicts')}><Badge color="purple" text={`${run.conflicts ?? 0}`} /></Tooltip>
            </Space>
            <div style={{ marginTop: 8 }}>
              {Object.entries(run.units_by_status || {}).filter(([s]) => s !== 'preserved').map(([s, n]) => (
                <span key={s} style={{ marginRight: 4 }}><UnitStatusTag s={s} /><span className="small muted">{n}</span></span>
              ))}
            </div>
          </div>
        ) : run.status === 'error' ? (
          <Tag color="red">{t('analysis.error')}</Tag>
        ) : (
          <Progress percent={Math.round(run.progress * 100)} size="small" status="active" />
        )
      ) : (
        <Typography.Text type="secondary">{t('dashboard.noRun')}</Typography.Text>
      )}
      <div className="small muted" style={{ marginTop: 10 }}>
        {p.owner} · {dayjs(p.updated_at).format('DD.MM.YYYY HH:mm')}
      </div>
    </Card>
  )
}

export default function DashboardPage() {
  const { t } = useTranslation()
  const { user } = useAuth()
  const editable = canEdit(user)
  const nav = useNavigate()
  const qc = useQueryClient()
  const { message } = AntApp.useApp()
  const meta = useMeta()
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const projects = useQuery({
    queryKey: ['projects'],
    queryFn: () => api<Project[]>('/projects'),
    refetchInterval: (query) => (query.state.data?.some((p) => p.last_run && ['pending', 'running'].includes(p.last_run.status)) ? 2000 : false),
  })
  const demo = useMutation({
    mutationFn: (key: string) => api<Project>(`/projects/demo?key=${key}`, { method: 'POST' }),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ['projects'] })
      nav(`/projects/${p.id}/documents`)
    },
    onError: (e: Error) => message.error(e.message),
  })
  const list = useMemo(
    () => (projects.data || []).filter((p) => !q || (p.name + p.description).toLowerCase().includes(q.toLowerCase())),
    [projects.data, q],
  )
  // демо-комплекты: открываем существующий проект или создаём новый
  const openDemo = (set: { key: string; name: string }) => {
    const existing = projects.data?.find((p) => p.is_demo && p.name === set.name)
    if (existing) nav(`/projects/${existing.id}/analysis`)
    else if (editable) demo.mutate(set.key)
  }
  const demoSets = meta.data?.demo_sets || []

  return (
    <div className="page">
      <Card style={{ marginBottom: 20, background: 'linear-gradient(120deg,#eff6ff 0%,#ffffff 60%)' }}>
        <Row gutter={[24, 16]} align="middle">
          <Col xs={24} lg={10}>
            <Typography.Title level={3} style={{ marginTop: 0 }}>
              {t('dashboard.hello', { name: user?.full_name || user?.email })}
            </Typography.Title>
            <Typography.Paragraph type="secondary">{t('dashboard.intro')}</Typography.Paragraph>
            <Space wrap>
              {editable && (
                <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>{t('nav.newProject')}</Button>
              )}
              {demoSets.length > 0 && (
                <Dropdown trigger={['click']} menu={{
                  items: demoSets.map((d) => ({ key: d.key, label: d.name, onClick: () => openDemo(d) })),
                }}>
                  <Tooltip title={t('dashboard.demoHint')}>
                    <Button icon={<ExperimentOutlined />} loading={demo.isPending}>
                      {t('dashboard.demo')} <DownOutlined />
                    </Button>
                  </Tooltip>
                </Dropdown>
              )}
            </Space>
          </Col>
          <Col xs={24} lg={14}>
            <Steps
              responsive
              items={[
                { title: t('dashboard.step1'), description: t('dashboard.step1d'), icon: <FolderAddOutlined /> },
                { title: t('dashboard.step2'), description: t('dashboard.step2d'), icon: <CloudUploadOutlined /> },
                { title: t('dashboard.step3'), description: t('dashboard.step3d'), icon: <ThunderboltOutlined /> },
                { title: t('dashboard.step4'), description: t('dashboard.step4d'), icon: <FileDoneOutlined /> },
              ]}
            />
          </Col>
        </Row>
      </Card>

      <div className="page-title">
        <h2>{t('dashboard.projects')}</h2>
        <Input allowClear prefix={<SearchOutlined />} placeholder={t('dashboard.search')} style={{ maxWidth: 320 }}
          value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {projects.isLoading ? (
        <Card loading />
      ) : list.length === 0 ? (
        <Card>
          <Empty description={<><b>{t('dashboard.empty')}</b><br />{t('dashboard.emptyHint')}</>} />
        </Card>
      ) : (
        <Row gutter={[16, 16]}>
          {list.map((p) => (
            <Col key={p.id} xs={24} md={12} xl={8}>
              <ProjectCard p={p} />
            </Col>
          ))}
        </Row>
      )}
      <NewProjectModal open={open} onClose={() => setOpen(false)} />
    </div>
  )
}
