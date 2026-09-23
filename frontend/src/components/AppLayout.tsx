import { KeyOutlined, LogoutOutlined, QuestionCircleOutlined, SafetyOutlined, UserOutlined } from '@ant-design/icons'
import { Alert, Avatar, Dropdown, Form, Input, Layout, Menu, Modal, Space, Tag, App as AntApp } from 'antd'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { api, type Scope } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { AiBadge, Brand, LangSwitch } from './common'

/** Смена пароля. forced — временный пароль от администратора: окно нельзя закрыть, только сменить пароль или выйти. */
export function ChangePasswordModal({ open, onClose, scope = 'app', forced = false, onLogout }: {
  open: boolean; onClose: () => void; scope?: Scope; forced?: boolean; onLogout?: () => void
}) {
  const { t } = useTranslation()
  const { message } = AntApp.useApp()
  const [form] = Form.useForm()
  const [busy, setBusy] = useState(false)
  return (
    <Modal
      open={open}
      title={t('common.changePassword')}
      onCancel={forced ? onLogout : onClose}
      cancelText={forced ? t('common.logout') : undefined}
      closable={!forced}
      maskClosable={!forced}
      keyboard={!forced}
      confirmLoading={busy}
      onOk={async () => {
        const v = await form.validateFields()
        setBusy(true)
        try {
          await api('/auth/change-password', { body: v, scope })
          message.success(t('common.passwordChanged'))
          form.resetFields()
          onClose()
        } catch (e: any) {
          message.error(e.message)
        } finally {
          setBusy(false)
        }
      }}
    >
      {forced && <Alert type="warning" showIcon message={t('common.mustChangePassword')} style={{ marginBottom: 16 }} />}
      <Form form={form} layout="vertical">
        <Form.Item name="old_password" label={t('common.oldPassword')} rules={[{ required: true }]}>
          <Input.Password autoComplete="current-password" />
        </Form.Item>
        <Form.Item name="new_password" label={t('common.newPassword')} rules={[{ required: true, min: 8, message: t('common.minPassword') }]}>
          <Input.Password autoComplete="new-password" />
        </Form.Item>
      </Form>
    </Modal>
  )
}

export default function AppLayout() {
  const { t } = useTranslation()
  const { user, logout, refresh } = useAuth()
  const nav = useNavigate()
  const loc = useLocation()
  // после сброса пароля администратором пользователь сначала задаёт свой (сервер до этого отвечает 403)
  const forced = !!user?.must_change_password
  const [pwdOpen, setPwdOpen] = useState(false)
  const selected = loc.pathname.startsWith('/help') ? 'help' : 'projects'

  const items = [
    { key: 'role', label: <Tag color="blue">{t(`roles.${user?.role}`)}</Tag>, disabled: true },
    { key: 'pwd', icon: <KeyOutlined />, label: t('common.changePassword'), onClick: () => setPwdOpen(true) },
    ...(user?.role === 'admin'
      ? [{ key: 'admin', icon: <SafetyOutlined />, label: t('nav.admin'), onClick: () => nav('/admin') }]
      : []),
    { type: 'divider' as const },
    { key: 'logout', icon: <LogoutOutlined />, danger: true, label: t('common.logout'), onClick: () => { logout(); nav('/login') } },
  ]

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Header className="app-header">
        <Space size={28} align="center">
          <Link to="/" style={{ color: 'inherit' }}>
            <Brand />
          </Link>
          <Menu
            mode="horizontal"
            selectedKeys={[selected]}
            style={{ borderBottom: 'none', minWidth: 360 }}
            items={[
              { key: 'projects', label: <Link to="/">{t('nav.projects')}</Link> },
              { key: 'help', icon: <QuestionCircleOutlined />, label: <Link to="/help">{t('nav.help')}</Link> },
            ]}
          />
        </Space>
        <Space size={12}>
          <AiBadge />
          <LangSwitch size="small" />
          <Dropdown menu={{ items }} trigger={['click']}>
            <Space style={{ cursor: 'pointer' }}>
              <Avatar size="small" icon={<UserOutlined />} style={{ background: '#1d4ed8' }} />
              <span>{user?.full_name || user?.email}</span>
            </Space>
          </Dropdown>
        </Space>
      </Layout.Header>
      <Layout.Content>
        {!forced && <Outlet />}
      </Layout.Content>
      <ChangePasswordModal open={pwdOpen || forced} forced={forced} onClose={() => { setPwdOpen(false); refresh() }}
        onLogout={() => { logout(); nav('/login') }} />
    </Layout>
  )
}
