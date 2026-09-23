import { useQuery } from '@tanstack/react-query'
import { Card, Descriptions, Tag } from 'antd'
import { useTranslation } from 'react-i18next'
import { adminApi } from './DashboardPage'

export default function SystemPage() {
  const { t } = useTranslation()
  const q = useQuery({ queryKey: ['admin-system'], queryFn: () => adminApi<any>('/admin/system') })
  const s = q.data
  const yes = (v: boolean) => (v ? <Tag color="green">OK</Tag> : <Tag color="red">—</Tag>)
  return (
    <>
      <div className="page-title"><h2>{t('admin.system')}</h2></div>
      <Card loading={q.isLoading} style={{ maxWidth: 900 }}>
        {s && (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label={t('admin.sys.python')}>{s.python} · {s.platform}</Descriptions.Item>
            <Descriptions.Item label={t('admin.sys.db')}>{s.database}</Descriptions.Item>
            <Descriptions.Item label={t('admin.sys.dataDir')}>{s.data_dir}</Descriptions.Item>
            <Descriptions.Item label={t('admin.sys.disk')}>{s.disk_free_gb}</Descriptions.Item>
            <Descriptions.Item label={t('admin.sys.ocr')}>{yes(s.ocr.available)} {s.ocr.langs}</Descriptions.Item>
            <Descriptions.Item label={t('admin.sys.pdf')}>{yes(s.pdf_export)}</Descriptions.Item>
            <Descriptions.Item label={t('admin.sys.frontend')}>{yes(s.frontend_built)}</Descriptions.Item>
          </Descriptions>
        )}
      </Card>
    </>
  )
}
