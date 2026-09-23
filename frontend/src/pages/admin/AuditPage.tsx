import { useQuery } from '@tanstack/react-query'
import { Input, Select, Space, Table, Tag, Typography } from 'antd'
import dayjs from 'dayjs'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import ru from '../../i18n/ru'
import { adminApi } from './DashboardPage'

export default function AuditPage() {
  const { t } = useTranslation()
  const [action, setAction] = useState<string | undefined>()
  const [user, setUser] = useState('')
  const q = useQuery({
    queryKey: ['admin-audit', action, user],
    queryFn: () => adminApi<any[]>(`/admin/audit?limit=500${action ? `&action=${action}` : ''}${user ? `&user=${encodeURIComponent(user)}` : ''}`),
  })
  return (
    <>
      <div className="page-title">
        <h2>{t('admin.audit')}</h2>
        <Space>
          <Select allowClear placeholder={t('admin.auditCols.action')} style={{ width: 260 }} value={action} onChange={setAction}
            options={Object.keys(ru.admin.actions).map((a) => ({ value: a, label: t(`admin.actions.${a}`) }))} />
          <Input.Search allowClear placeholder={t('admin.auditCols.user')} onSearch={setUser} style={{ width: 220 }} />
        </Space>
      </div>
      <Table size="small" rowKey="id" loading={q.isLoading} dataSource={q.data || []} pagination={{ pageSize: 30 }}
        columns={[
          { title: t('admin.auditCols.time'), dataIndex: 'created_at', width: 150, render: (d) => dayjs(d).format('DD.MM.YYYY HH:mm:ss') },
          { title: t('admin.auditCols.user'), dataIndex: 'user', width: 220, render: (u) => u || '—' },
          { title: t('admin.auditCols.action'), dataIndex: 'action', width: 240, render: (a) => (
            <Tag color={a.includes('failed') || a.includes('denied') ? 'red' : a.includes('delete') ? 'orange' : 'blue'}>{t(`admin.actions.${a}`, { defaultValue: a })}</Tag>) },
          { title: t('admin.auditCols.entity'), render: (_, r) => (r.entity ? `${r.entity} #${r.entity_id}` : '—'), width: 140 },
          { title: t('admin.auditCols.details'), dataIndex: 'details', render: (d) => <Typography.Text className="small" type="secondary">{Object.keys(d || {}).length ? JSON.stringify(d) : ''}</Typography.Text> },
          { title: t('admin.auditCols.ip'), dataIndex: 'ip', width: 120 },
        ]} />
    </>
  )
}
