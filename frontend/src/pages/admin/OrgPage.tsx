import { SaveOutlined } from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Card, Col, Form, Input, Row, App as AntApp } from 'antd'
import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { adminApi } from './DashboardPage'

const FIELDS = ['company_name', 'company_name_kz', 'city', 'approver_title', 'approver_title_kz', 'approver_name']

export default function OrgPage() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const { message } = AntApp.useApp()
  const [form] = Form.useForm()
  const q = useQuery({ queryKey: ['admin-org'], queryFn: () => adminApi<any>('/admin/settings/org') })
  useEffect(() => { if (q.data) form.setFieldsValue(q.data) }, [q.data, form])
  return (
    <>
      <div className="page-title"><h2>{t('admin.org')}</h2></div>
      <Card loading={q.isLoading} style={{ maxWidth: 900 }}>
        <Form form={form} layout="vertical">
          <Row gutter={16}>
            {FIELDS.map((f) => (
              <Col xs={24} md={12} key={f}><Form.Item name={f} label={t(`admin.orgF.${f}`)}><Input /></Form.Item></Col>
            ))}
          </Row>
        </Form>
        <Button type="primary" icon={<SaveOutlined />} onClick={async () => {
          try {
            await adminApi('/admin/settings/org', { method: 'PUT', body: { values: form.getFieldsValue() } })
            message.success(t('common.saved'))
            qc.invalidateQueries({ queryKey: ['admin-org'] })
          } catch (e: any) {
            message.error(e.message)
          }
        }}>{t('common.save')}</Button>
      </Card>
    </>
  )
}
