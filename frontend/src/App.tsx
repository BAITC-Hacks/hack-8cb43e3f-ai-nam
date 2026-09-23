import { Spin } from 'antd'
import type { ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useAdminAuth, useAuth } from './auth/AuthContext'
import AdminLayout from './components/AdminLayout'
import AppLayout from './components/AppLayout'
import AdminLoginPage from './pages/admin/AdminLoginPage'
import AdminAudit from './pages/admin/AuditPage'
import AdminDashboard from './pages/admin/DashboardPage'
import AdminModel from './pages/admin/ModelPage'
import AdminOrg from './pages/admin/OrgPage'
import AdminRules from './pages/admin/RulesPage'
import AdminSystem from './pages/admin/SystemPage'
import AdminUsers from './pages/admin/UsersPage'
import DashboardPage from './pages/DashboardPage'
import HelpPage from './pages/HelpPage'
import LoginPage from './pages/LoginPage'
import ProjectPage from './pages/ProjectPage'

function Loader() {
  return (
    <div style={{ height: '100vh', display: 'grid', placeItems: 'center' }}>
      <Spin size="large" />
    </div>
  )
}

function RequireUser({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const loc = useLocation()
  if (loading) return <Loader />
  if (!user) return <Navigate to="/login" replace state={{ from: loc.pathname }} />
  return <>{children}</>
}

function RequireAdmin({ children }: { children: ReactNode }) {
  const { user, loading } = useAdminAuth()
  if (loading) return <Loader />
  if (!user) return <Navigate to="/admin/login" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/admin/login" element={<AdminLoginPage />} />
      <Route
        path="/admin"
        element={
          <RequireAdmin>
            <AdminLayout />
          </RequireAdmin>
        }
      >
        <Route index element={<AdminDashboard />} />
        <Route path="users" element={<AdminUsers />} />
        <Route path="model" element={<AdminModel />} />
        <Route path="rules" element={<AdminRules />} />
        <Route path="org" element={<AdminOrg />} />
        <Route path="audit" element={<AdminAudit />} />
        <Route path="system" element={<AdminSystem />} />
      </Route>
      <Route
        path="/"
        element={
          <RequireUser>
            <AppLayout />
          </RequireUser>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="projects/:id" element={<ProjectPage />} />
        <Route path="projects/:id/:tab" element={<ProjectPage />} />
        <Route path="help" element={<HelpPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
