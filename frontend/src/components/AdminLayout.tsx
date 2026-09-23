import {
  AppstoreOutlined, AuditOutlined, BankOutlined, DashboardOutlined, LogoutOutlined, RobotOutlined,
  SettingOutlined, SlidersOutlined, TeamOutlined,
} from '@ant-design/icons'
import { Button, Layout, Menu, Space, Tag, Typography } from 'antd'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAdminAuth } from '../auth/AuthContext'
import { Brand, LangSwitch } from './common'

export default function AdminLayout() {
  const { t } = useTranslation()
  const { user, logout } = useAdminAuth()
  const nav = useNavigate()
  const loc = useLocation()
  const [collapsed, setCollapsed] = useState(false)
  const key = loc.pathname.replace(/^\/admin\/?/, '').split('/')[0] || 'dashboard'

  const items = [
    { key: 'dashboard', icon: <DashboardOutlined />, label: t('admin.dashboard') },
    { key: 'users', icon: <TeamOutlined />, label: t('admin.users') },
    { key: 'model', icon: <RobotOutlined />, label: t('admin.model') },
    { key: 'rules', icon: <SlidersOutlined />, label: t('admin.rules') },
    { key: 'org', icon: <BankOutlined />, label: t('admin.org') },
    { key: 'audit', icon: <AuditOutlined />, label: t('admin.audit') },
    { key: 'system', icon: <SettingOutlined />, label: t('admin.system') },
  ]

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Sider theme="dark" collapsible collapsed={collapsed} onCollapse={setCollapsed} width={240}
        style={{ background: '#0f0b24' }}>
        <div style={{ padding: '18px 16px', color: '#fff' }}>
          <Brand admin collapsed={collapsed} />
          {!collapsed && <div style={{ color: '#a78bfa', fontSize: 12, marginTop: 6 }}>{t('admin.title')}</div>}
        </div>
        <Menu theme="dark" mode="inline" selectedKeys={[key]} items={items} style={{ background: 'transparent' }}
          onClick={(e) => nav(e.key === 'dashboard' ? '/admin' : `/admin/${e.key}`)} />
      </Layout.Sider>
      <Layout>
        <Layout.Header className="app-header">
          <Space>
            <Tag color="purple">{t('nav.admin')}</Tag>
            <Typography.Text type="secondary">{items.find((i) => i.key === key)?.label}</Typography.Text>
          </Space>
          <Space>
            <LangSwitch size="small" />
            <Button icon={<AppstoreOutlined />} onClick={() => nav('/')}>{t('admin.backToApp')}</Button>
            <Typography.Text>{user?.email}</Typography.Text>
            <Button icon={<LogoutOutlined />} onClick={() => { logout(); nav('/admin/login') }}>{t('common.logout')}</Button>
          </Space>
        </Layout.Header>
        <Layout.Content>
          <div className="page">
            <Outlet />
          </div>
        </Layout.Content>
      </Layout>
    </Layout>
  )
}
