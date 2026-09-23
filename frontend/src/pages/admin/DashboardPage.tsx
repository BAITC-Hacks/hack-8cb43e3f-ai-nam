import { CheckCircleTwoTone, CloseCircleTwoTone, RobotOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { Card, Col, List, Row, Space, Statistic, Tag, Typography } from 'antd'
import dayjs from 'dayjs'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { api } from '../../api/client'

export const adminApi = <T,>(path: string, opts: Parameters<typeof api>[1] = {}) => api<T>(path, { ...opts, scope: 'admin' })

const ok = (v: boolean) => (v ? <CheckCircleTwoTone twoToneColor="#16a34a" /> : <CloseCircleTwoTone twoToneColor="#dc2626" />)

export default function AdminDashboard() {
  const { t } = useTranslation()
  const nav = useNavigate()
  const q = useQuery({ queryKey: ['admin-stats'], queryFn: () => adminApi<any>('/admin/stats'), refetchInterval: 10_000 })
  const s = q.data
  return (
    <>
      <div className="page-title"><h2>{t('admin.dashboard')}</h2></div>
      <Row gutter={[16, 16]}>
        {[
          ['users', s?.users, `${s?.active_users ?? 0} ${t('admin.active').toLowerCase()}`],
          ['projects', s?.projects],
          ['documents', s?.documents, s?.documents_error ? `${s.documents_error} ${t('admin.stats.errors')}` : undefined],
          ['runs', Object.values(s?.runs || {}).reduce((a: number, b: any) => a + b, 0)],
          ['files', s?.files],
        ].map(([k, v, sub]) => (
          <Col xs={12} md={8} xl={4} key={k as string}>
            <Card loading={q.isLoading} className="stat-card">
              <Statistic title={t(`admin.stats.${k}`)} value={v as number} />
              {sub && <div className="small muted">{sub as string}</div>}
            </Card>
          </Col>
        ))}
        <Col xs={24} md={8} xl={4}>
          <Card loading={q.isLoading} className="stat-card" hoverable onClick={() => nav('/admin/model')}>
            <Statistic title={t('admin.model')} value={s?.llm.enabled ? s.llm.model : t('ai.demo')} prefix={<RobotOutlined />} valueStyle={{ fontSize: 16 }} />
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card title={t('admin.health')} loading={q.isLoading}>
            <List size="small" dataSource={[
              [t('admin.model'), s?.llm.enabled, s?.llm.enabled ? `${s.llm.provider}: ${s.llm.model}` : t('ai.demoHint')],
              ['OCR (Tesseract)', s?.ocr, ''],
              ['PDF (LibreOffice)', s?.pdf, ''],
            ]} renderItem={([n, v, d]: any) => (
              <List.Item><Space>{ok(!!v)}<b>{n}</b></Space><span className="small muted">{d}</span></List.Item>
            )} />
            <div style={{ marginTop: 12 }}>
              {Object.entries(s?.users_by_role || {}).map(([r, n]) => <Tag key={r}>{t(`roles.${r}`)}: {n as number}</Tag>)}
            </div>
          </Card>
        </Col>
        <Col xs={24} lg={16}>
          <Card title={t('admin.recent')} loading={q.isLoading} extra={<a onClick={() => nav('/admin/audit')}>{t('admin.audit')}</a>}>
            <List size="small" dataSource={s?.recent || []} renderItem={(a: any) => (
              <List.Item>
                <Space>
                  <Typography.Text type="secondary">{dayjs(a.created_at).format('DD.MM HH:mm')}</Typography.Text>
                  <Tag color={a.action.includes('failed') || a.action.includes('denied') ? 'red' : 'blue'}>{t(`admin.actions.${a.action}`, { defaultValue: a.action })}</Tag>
                  <span>{a.user || '—'}</span>
                </Space>
              </List.Item>
            )} />
          </Card>
        </Col>
      </Row>
    </>
  )
}
