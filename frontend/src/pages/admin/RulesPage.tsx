import { SaveOutlined, UndoOutlined } from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Card, Checkbox, Col, Form, InputNumber, Row, Select, Slider, Space, App as AntApp } from 'antd'
import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { adminApi } from './DashboardPage'

export default function RulesPage() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const { message } = AntApp.useApp()
  const [form] = Form.useForm()
  const q = useQuery({ queryKey: ['admin-rules'], queryFn: () => adminApi<any>('/admin/settings/analysis') })
  useEffect(() => { if (q.data) form.setFieldsValue(q.data) }, [q.data, form])
  const save = async () => {
    try {
      await adminApi('/admin/settings/analysis', { method: 'PUT', body: { values: await form.validateFields() } })
      message.success(t('common.saved'))
      qc.invalidateQueries({ queryKey: ['admin-rules'] })
    } catch (e: any) {
      message.error(e.message)
    }
  }
  const slider = (name: string) => (
    <Form.Item name={name} label={t(`admin.rulesF.${name}`)}>
      <Slider min={0.2} max={0.95} step={0.01} marks={{ 0.2: '0.2', 0.5: '0.5', 0.8: '0.8' }} />
    </Form.Item>
  )
  return (
    <>
      <div className="page-title"><h2>{t('admin.rules')}</h2></div>
      <Alert type="info" showIcon message={t('admin.rulesIntro')} style={{ marginBottom: 16 }} />
      <Card loading={q.isLoading}>
        <Form form={form} layout="vertical">
          <Row gutter={24}>
            <Col xs={24} md={12}>{slider('match_high')}</Col>
            <Col xs={24} md={12}>{slider('match_low')}</Col>
            <Col xs={24} md={12}>{slider('duplicate')}</Col>
            <Col xs={24} md={12}>{slider('unit_name')}</Col>
            <Col xs={24} md={12}>
              <Form.Item name="min_function_words" label={t('admin.rulesF.min_function_words')}><InputNumber min={1} max={20} /></Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item name="function_kinds" label={t('admin.rulesF.function_kinds')}>
                <Checkbox.Group options={['function', 'task', 'duty', 'right', 'responsibility'].map((k) => ({ value: k, label: t(`kinds.${k}`) }))} />
              </Form.Item>
            </Col>
            <Col span={24}>
              <Form.Item name="generic_phrases" label={t('admin.rulesF.generic_phrases')}>
                <Select mode="tags" tokenSeparators={['\n']} />
              </Form.Item>
            </Col>
          </Row>
        </Form>
        <Space>
          <Button type="primary" icon={<SaveOutlined />} onClick={save}>{t('common.save')}</Button>
          <Button icon={<UndoOutlined />} onClick={async () => { await adminApi('/admin/settings/analysis/reset', { method: 'POST' }); qc.invalidateQueries({ queryKey: ['admin-rules'] }) }}>{t('common.reset')}</Button>
        </Space>
      </Card>
    </>
  )
}
