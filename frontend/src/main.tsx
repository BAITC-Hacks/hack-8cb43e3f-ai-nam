import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntApp, ConfigProvider, theme } from 'antd'
import kkKZ from 'antd/locale/kk_KZ'
import ruRU from 'antd/locale/ru_RU'
import dayjs from 'dayjs'
import 'dayjs/locale/kk'
import 'dayjs/locale/ru'
import React from 'react'
import ReactDOM from 'react-dom/client'
import { useTranslation } from 'react-i18next'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { AdminAuthProvider, AuthProvider } from './auth/AuthContext'
import './i18n'
import './styles.css'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 5_000 } },
})

function Root() {
  const { i18n } = useTranslation()
  const kz = i18n.language === 'kz'
  dayjs.locale(kz ? 'kk' : 'ru')
  return (
    <ConfigProvider
      locale={kz ? kkKZ : ruRU}
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: '#1d4ed8',
          borderRadius: 8,
          fontFamily: "Inter, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
          colorBgLayout: '#f4f6fb',
        },
        components: { Layout: { headerBg: '#ffffff', siderBg: '#ffffff' }, Card: { borderRadiusLG: 12 } },
      }}
    >
      <AntApp>
        <BrowserRouter>
          <AuthProvider>
            <AdminAuthProvider>
              <App />
            </AdminAuthProvider>
          </AuthProvider>
        </BrowserRouter>
      </AntApp>
    </ConfigProvider>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <Root />
    </QueryClientProvider>
  </React.StrictMode>,
)
