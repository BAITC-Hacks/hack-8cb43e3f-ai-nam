import {
  AuditOutlined, BranchesOutlined, FileSearchOutlined, LockOutlined, MailOutlined, RobotOutlined,
  SafetyCertificateOutlined, SettingOutlined, TeamOutlined,
} from '@ant-design/icons'
import { Alert, Button, Divider, Form, Input, Space, Typography } from 'antd'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAdminAuth, useAuth } from '../auth/AuthContext'
import { Brand, LangSwitch } from '../components/common'

export function AuthScreen({ admin }: { admin: boolean }) {
  const { t } = useTranslation()
  const appAuth = useAuth()
  const adminAuth = useAdminAuth()
  const auth = admin ? adminAuth : appAuth
  const nav = useNavigate()
  const loc = useLocation() as { state?: { from?: string } }
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (auth.user) return <Navigate to={admin ? '/admin' : loc.state?.from || '/'} replace />

  const features = admin
    ? [
        { icon: <TeamOutlined />, text: t('admin.users') },
        { icon: <RobotOutlined />, text: t('admin.model') },
        { icon: <SettingOutlined />, text: t('admin.rules') },
        { icon: <AuditOutlined />, text: t('admin.audit') },
      ]
    : [
        { icon: <FileSearchOutlined />, text: t('findingType.loss') + ', ' + t('findingType.duplication').toLowerCase() },
        { icon: <SafetyCertificateOutlined />, text: t('findingType.conflict') },
        { icon: <BranchesOutlined />, text: t('structure.changes') + ' · ' + t('structure.importChart') },
      ]

  const onFinish = async (v: { email: string; password: string }) => {
    setError(null)
    setBusy(true)
    try {
      await auth.login(v.email, v.password)
      nav(admin ? '/admin' : loc.state?.from || '/', { replace: true })
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-page">
      <div className={`auth-hero ${admin ? 'admin' : ''}`}>
        <div style={{ color: '#fff' }}>
          <Brand admin={admin} />
        </div>
        <div>
          <Typography.Title level={1}>{admin ? t('auth.adminTitle') : t('app.subtitle')}</Typography.Title>
          <p>{admin ? t('auth.adminHint') : t('auth.userHint')}</p>
          <div style={{ marginTop: 24 }}>
            {features.map((f, i) => (
              <div className="feature" key={i}>
                {f.icon}
                <span>{f.text}</span>
              </div>
            ))}
          </div>
        </div>
        <div style={{ color: 'rgba(255,255,255,.6)', fontSize: 12 }}>{t('analysis.disclaimer')}</div>
      </div>
      <div className="auth-form">
        <div className="box">
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 24 }}>
            <LangSwitch size="small" />
          </div>
          <Typography.Title level={3} style={{ marginBottom: 4 }}>
            {admin ? (
              <Space>
                <LockOutlined style={{ color: '#7c3aed' }} />
                {t('auth.adminTitle')}
              </Space>
            ) : (
              t('auth.title')
            )}
          </Typography.Title>
          <Typography.Paragraph type="secondary">{admin ? t('auth.adminHint') : t('app.subtitle')}</Typography.Paragraph>
          {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />}
          <Form layout="vertical" onFinish={onFinish} requiredMark={false}>
            <Form.Item name="email" label={t('auth.email')} rules={[{ required: true }]}>
              <Input size="large" prefix={<MailOutlined />} autoComplete="username" autoFocus />
            </Form.Item>
            <Form.Item name="password" label={t('auth.password')} rules={[{ required: true }]}>
              <Input.Password size="large" prefix={<LockOutlined />} autoComplete="current-password" />
            </Form.Item>
            <Button type="primary" htmlType="submit" size="large" block loading={busy}
              style={admin ? { background: '#7c3aed' } : undefined}>
              {t('auth.signIn')}
            </Button>
          </Form>
          <Divider />
          {admin ? (
            <Link to="/login">{t('auth.toApp')}</Link>
          ) : (
            <Space direction="vertical" size={4} style={{ width: '100%' }}>
              <Link to="/admin/login">
                <LockOutlined /> {t('auth.toAdmin')}
              </Link>
              <Typography.Text type="secondary" className="small">
                {t('auth.demo')}: admin@example.com / admin12345 · analyst@example.com / analyst12345 · viewer@example.com / viewer12345
              </Typography.Text>
              <Typography.Text type="secondary" className="small">{t('auth.demoNote')}</Typography.Text>
            </Space>
          )}
        </div>
      </div>
    </div>
  )
}

export default function LoginPage() {
  return <AuthScreen admin={false} />
}
