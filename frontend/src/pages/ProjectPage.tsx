import { ApartmentOutlined, CommentOutlined, EditOutlined, FileDoneOutlined, FolderOpenOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Breadcrumb, Card, Result, Space, Spin, Steps, Tabs, Tag, Typography, App as AntApp } from 'antd'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { DocBrief, Project, Run } from '../api/types'
import { canEdit, useAuth } from '../auth/AuthContext'
import { SourceProvider } from '../components/DocumentViewer'
import AnalysisTab from './project/AnalysisTab'
import AssistantTab from './project/AssistantTab'
import ConclusionTab from './project/ConclusionTab'
import DocumentsTab from './project/DocumentsTab'
import StructureTab from './project/StructureTab'

export const useProject = (id: number) =>
  useQuery({ queryKey: ['project', id], queryFn: () => api<Project>(`/projects/${id}`) })

export const useDocuments = (id: number) =>
  useQuery({
    queryKey: ['documents', id],
    queryFn: () => api<DocBrief[]>(`/projects/${id}/documents`),
    refetchInterval: (q) => (q.state.data?.some((d) => d.status === 'uploaded' || d.status === 'processing') ? 1500 : false),
  })

export const useLatestRun = (projectId: number) =>
  useQuery({
    queryKey: ['latest-run', projectId],
    queryFn: async () => {
      const runs = await api<Run[]>(`/projects/${projectId}/analysis`)
      if (!runs.length) return null
      return api<Run>(`/analysis/${runs[0].id}`)
    },
    refetchInterval: (q) => (q.state.data && ['pending', 'running'].includes(q.state.data.status) ? 1200 : false),
  })

const TABS = ['documents', 'structure', 'analysis', 'conclusion', 'assistant'] as const

export default function ProjectPage() {
  const { t } = useTranslation()
  const { id, tab } = useParams()
  const pid = Number(id)
  const nav = useNavigate()
  const { user } = useAuth()
  const qc = useQueryClient()
  const { message } = AntApp.useApp()
  const project = useProject(pid)
  const docs = useDocuments(pid)
  const run = useLatestRun(pid)
  const active = (TABS as readonly string[]).includes(tab || '') ? (tab as string) : (run.data ? 'analysis' : 'documents')

  if (project.isLoading) return <div className="page"><Spin /></div>
  if (!project.data) return <Result status="404" title={t('project.notFound')} extra={<Link to="/">{t('nav.projects')}</Link>} />
  const p = project.data
  const hasBoth = (docs.data || []).some((d) => d.side === 'before' && d.status === 'parsed') &&
    (docs.data || []).some((d) => d.side === 'after' && d.status === 'parsed')
  const done = run.data?.status === 'done'
  const stepIndex = done ? 3 : hasBoth ? 2 : (docs.data?.length ? 1 : 0)

  const rename = async (name: string) => {
    if (!name.trim() || name === p.name) return
    try {
      await api(`/projects/${pid}`, { method: 'PATCH', body: { name } })
      qc.invalidateQueries({ queryKey: ['project', pid] })
    } catch (e: any) {
      message.error(e.message)
    }
  }

  return (
    <SourceProvider>
      <div className="page">
        <Breadcrumb items={[{ title: <Link to="/">{t('nav.projects')}</Link> }, { title: p.name }]} style={{ marginBottom: 8 }} />
        <div className="page-title">
          <Space direction="vertical" size={0}>
            <Space>
              <Typography.Title level={3} style={{ margin: 0 }}
                editable={canEdit(user) ? { onChange: rename, icon: <EditOutlined style={{ fontSize: 16 }} /> } : false}>
                {p.name}
              </Typography.Title>
              {p.is_demo && <Tag color="purple">DEMO</Tag>}
            </Space>
            {p.description && <Typography.Text type="secondary">{p.description}</Typography.Text>}
          </Space>
        </div>
        <Card size="small" style={{ marginBottom: 16 }}>
          <Steps
            size="small"
            current={stepIndex}
            onChange={(i) => nav(`/projects/${pid}/${['documents', 'structure', 'analysis', 'conclusion'][i]}`)}
            items={[
              { title: t('project.wizard.documents'), icon: <FolderOpenOutlined /> },
              { title: t('project.wizard.structure'), icon: <ApartmentOutlined /> },
              { title: t('project.wizard.analysis'), icon: <ThunderboltOutlined /> },
              { title: t('project.wizard.conclusion'), icon: <FileDoneOutlined /> },
            ]}
          />
        </Card>
        <Tabs
          activeKey={active}
          onChange={(k) => nav(`/projects/${pid}/${k}`)}
          destroyInactiveTabPane
          items={[
            { key: 'documents', label: <span><FolderOpenOutlined /> {t('project.tabs.documents')}</span>, children: <DocumentsTab projectId={pid} /> },
            { key: 'structure', label: <span><ApartmentOutlined /> {t('project.tabs.structure')}</span>, children: <StructureTab projectId={pid} /> },
            { key: 'analysis', label: <span><ThunderboltOutlined /> {t('project.tabs.analysis')}</span>, children: <AnalysisTab projectId={pid} /> },
            { key: 'conclusion', label: <span><FileDoneOutlined /> {t('project.tabs.conclusion')}</span>, children: <ConclusionTab projectId={pid} /> },
            { key: 'assistant', label: <span><CommentOutlined /> {t('project.tabs.assistant')}</span>, children: <AssistantTab projectId={pid} /> },
          ]}
        />
      </div>
    </SourceProvider>
  )
}
