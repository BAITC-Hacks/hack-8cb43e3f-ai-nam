import { DeleteOutlined, KeyOutlined, LockOutlined, PlusOutlined, UnlockOutlined } from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag, Tooltip, Typography, App as AntApp } from 'antd'
import dayjs from 'dayjs'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { User } from '../../api/types'
import { useAdminAuth } from '../../auth/AuthContext'
import { adminApi } from './DashboardPage'

export default function UsersPage() {
  const { t } = useTranslation()
  const { user: me } = useAdminAuth()
  const qc = useQueryClient()
  const { message, modal } = AntApp.useApp()
  const users = useQuery({ queryKey: ['admin-users'], queryFn: () => adminApi<User[]>('/admin/users') })
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm()
  const [q, setQ] = useState('')
  const refresh = () => qc.invalidateQueries({ queryKey: ['admin-users'] })
  const call = async (fn: () => Promise<any>) => {
    try {
      const r = await fn()
      refresh()
      return r
    } catch (e: any) {
      message.error(e.message)
    }
  }
  const showPwd = (pwd: string) => modal.success({
    title: t('admin.resetPwd'),
    content: <Typography.Paragraph copyable={{ text: pwd }}>{t('admin.tempPassword', { pwd })}</Typography.Paragraph>,
  })
  const roleOptions = (['admin', 'analyst', 'viewer'] as const).map((r) => ({ value: r, label: t(`roles.${r}`) }))
  const data = (users.data || []).filter((u) => !q || (u.email + u.full_name).toLowerCase().includes(q.toLowerCase()))

  return (
    <>
      <div className="page-title">
        <h2>{t('admin.users')}</h2>
        <Space>
          <Input.Search allowClear placeholder={t('common.search')} onChange={(e) => setQ(e.target.value)} />
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>{t('admin.userNew')}</Button>
        </Space>
      </div>
      <Table rowKey="id" loading={users.isLoading} dataSource={data} pagination={{ pageSize: 20 }}
        columns={[
          { title: t('common.fullName'), dataIndex: 'full_name', render: (v, u) => <Space direction="vertical" size={0}><b>{v || '—'}</b><span className="small muted">{u.email}</span></Space> },
          { title: t('common.role'), dataIndex: 'role', width: 200, render: (r, u) => (
            <Select size="small" value={r} style={{ width: 170 }} options={roleOptions} disabled={u.id === me?.id}
              onChange={(role) => call(() => adminApi(`/admin/users/${u.id}`, { method: 'PATCH', body: { role } }))} />) },
          { title: t('common.status'), dataIndex: 'is_active', width: 130, render: (a) => (a ? <Tag color="green">{t('admin.active')}</Tag> : <Tag color="red">{t('admin.blocked')}</Tag>) },
          { title: t('admin.lastLogin'), dataIndex: 'last_login_at', width: 160, render: (d) => (d ? dayjs(d).format('DD.MM.YYYY HH:mm') : '—') },
          { title: t('common.actions'), width: 170, render: (_, u) => (
            <Space>
              <Tooltip title={u.is_active ? t('admin.block') : t('admin.unblock')}>
                <Button size="small" icon={u.is_active ? <LockOutlined /> : <UnlockOutlined />} disabled={u.id === me?.id}
                  onClick={() => call(() => adminApi(`/admin/users/${u.id}`, { method: 'PATCH', body: { is_active: !u.is_active } }))} />
              </Tooltip>
              <Tooltip title={t('admin.resetPwd')}>
                <Button size="small" icon={<KeyOutlined />} onClick={async () => {
                  const r = await call(() => adminApi<{ temporary_password: string }>(`/admin/users/${u.id}/reset-password`, { method: 'POST' }))
                  if (r) showPwd(r.temporary_password)
                }} />
              </Tooltip>
              <Popconfirm title={t('common.confirmDelete')} onConfirm={() => call(() => adminApi(`/admin/users/${u.id}`, { method: 'DELETE' }))} disabled={u.id === me?.id}>
                <Button size="small" danger icon={<DeleteOutlined />} disabled={u.id === me?.id} />
              </Popconfirm>
            </Space>) },
        ]} />
      <Modal open={open} title={t('admin.userNew')} onCancel={() => setOpen(false)} onOk={async () => {
        const v = await form.validateFields()
        const r = await call(() => adminApi<any>('/admin/users', { body: { ...v, password: v.password || null } }))
        if (r) {
          setOpen(false)
          form.resetFields()
          if (r.temporary_password) showPwd(r.temporary_password)
        }
      }}>
        <Form form={form} layout="vertical" initialValues={{ role: 'analyst' }}>
          <Form.Item name="email" label={t('common.email')} rules={[{ required: true, type: 'email' }]}><Input /></Form.Item>
          <Form.Item name="full_name" label={t('common.fullName')}><Input /></Form.Item>
          <Form.Item name="role" label={t('common.role')}><Select options={roleOptions} /></Form.Item>
          <Form.Item name="password" label={t('admin.passwordOpt')} rules={[{ min: 8, message: t('common.minPassword') }]}><Input.Password /></Form.Item>
          <Alert type="info" showIcon message={`${t('roles.admin')} — ${t('admin.title').toLowerCase()}; ${t('roles.analyst')} — ${t('analysis.run').toLowerCase()}; ${t('roles.viewer')} — ${t('common.open').toLowerCase()}`} />
        </Form>
      </Modal>
    </>
  )
}
