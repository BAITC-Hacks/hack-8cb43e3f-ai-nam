import { ApiOutlined, CheckCircleOutlined, CloseCircleOutlined, SaveOutlined, UndoOutlined } from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert, Button, Card, Checkbox, Col, Divider, Form, Input, InputNumber, Radio, Row, Space, Tag, Typography, App as AntApp,
} from 'antd'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { adminApi } from './DashboardPage'

export default function ModelPage() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const { message } = AntApp.useApp()
  const [form] = Form.useForm()
  const cfg = useQuery({ queryKey: ['admin-llm'], queryFn: () => adminApi<any>('/admin/settings/llm') })
  const presets = useQuery({ queryKey: ['admin-presets'], queryFn: () => adminApi<any[]>('/admin/llm/presets') })
  const [test, setTest] = useState<any>(null)
  const [testing, setTesting] = useState(false)
  const provider = Form.useWatch('provider', form)
  useEffect(() => { if (cfg.data) form.setFieldsValue(cfg.data) }, [cfg.data, form])

  const save = async () => {
    const values = await form.validateFields()
    try {
      await adminApi('/admin/settings/llm', { method: 'PUT', body: { values } })
      message.success(t('common.saved'))
      qc.invalidateQueries({ queryKey: ['admin-llm'] })
      qc.invalidateQueries({ queryKey: ['meta'] })
    } catch (e: any) {
      message.error(e.message)
    }
  }
  const runTest = async () => {
    setTesting(true)
    setTest(null)
    try {
      setTest(await adminApi('/admin/llm/test', { body: { values: form.getFieldsValue() } }))
    } catch (e: any) {
      setTest({ ok: false, message: e.message })
    } finally {
      setTesting(false)
    }
  }

  return (
    <>
      <div className="page-title"><h2>{t('admin.model')}</h2></div>
      <Alert type="info" showIcon message={t('admin.llm.intro')} style={{ marginBottom: 16 }} />
      <Row gutter={16}>
        <Col xs={24} xl={15}>
          <Card loading={cfg.isLoading}>
            <Form form={form} layout="vertical">
              <Form.Item name="provider" label={t('admin.llm.provider')}>
                <Radio.Group optionType="button" options={[{ value: 'none', label: t('admin.llm.none') }, { value: 'openai', label: t('admin.llm.openai') }]} />
              </Form.Item>
              <div style={{ opacity: provider === 'none' ? 0.5 : 1 }}>
                <Row gutter={12}>
                  <Col span={14}><Form.Item name="base_url" label={t('admin.llm.baseUrl')}><Input placeholder="http://localhost:11434/v1" /></Form.Item></Col>
                  <Col span={10}><Form.Item name="api_key" label={t('admin.llm.apiKey')}><Input.Password placeholder="ollama / sk-…" /></Form.Item></Col>
                </Row>
                <Row gutter={12}>
                  <Col span={8}><Form.Item name="model" label={t('admin.llm.model')}><Input placeholder="qwen2.5:7b-instruct" /></Form.Item></Col>
                  <Col span={8}><Form.Item name="vision_model" label={t('admin.llm.vision')}><Input placeholder="qwen2.5vl:7b" /></Form.Item></Col>
                  <Col span={8}><Form.Item name="embed_model" label={t('admin.llm.embed')}><Input placeholder="bge-m3" /></Form.Item></Col>
                </Row>
                <Row gutter={12}>
                  <Col span={8}><Form.Item name="temperature" label={t('admin.llm.temperature')}><InputNumber min={0} max={1} step={0.1} style={{ width: '100%' }} /></Form.Item></Col>
                  <Col span={8}><Form.Item name="timeout" label={t('admin.llm.timeout')}><InputNumber min={5} max={600} style={{ width: '100%' }} /></Form.Item></Col>
                </Row>
                <Divider orientation="left" plain>{t('admin.llm.usage')}</Divider>
                <Space wrap>
                  {['verification', 'conclusion', 'extraction', 'chat'].map((k) => (
                    <Form.Item key={k} name={`use_for_${k}`} valuePropName="checked" style={{ marginBottom: 0 }}>
                      <Checkbox>{t(`admin.llm.${k}`)}</Checkbox>
                    </Form.Item>
                  ))}
                </Space>
                <Alert type="warning" showIcon style={{ marginTop: 16 }} message={t('admin.llm.privacy')} />
              </div>
            </Form>
            <Space style={{ marginTop: 16 }}>
              <Button type="primary" icon={<SaveOutlined />} onClick={save}>{t('common.save')}</Button>
              <Button icon={<ApiOutlined />} loading={testing} onClick={runTest}>{t('admin.llm.test')}</Button>
              <Button icon={<UndoOutlined />} onClick={async () => { await adminApi('/admin/settings/llm/reset', { method: 'POST' }); qc.invalidateQueries({ queryKey: ['admin-llm'] }); qc.invalidateQueries({ queryKey: ['meta'] }) }}>{t('common.reset')}</Button>
            </Space>
            {test && (
              <Alert style={{ marginTop: 16 }} type={test.ok ? 'success' : test.mode === 'demo' ? 'info' : 'error'} showIcon
                icon={test.ok ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
                message={test.ok ? t('admin.llm.testOk', { ms: test.latency_ms, reply: test.reply }) : test.message}
                description={
                  <>
                    {test.embeddings !== undefined && <div>Embeddings: {test.embeddings ? 'OK' : test.embeddings_error}</div>}
                    {test.models?.length > 0 && (
                      <div style={{ marginTop: 6 }}>{t('admin.llm.models')}: {test.models.map((m: string) => (
                        <Tag key={m} style={{ cursor: 'pointer' }} onClick={() => form.setFieldValue('model', m)}>{m}</Tag>))}</div>
                    )}
                    {test.models_error && <div className="small">{test.models_error}</div>}
                  </>
                } />
            )}
          </Card>
        </Col>
        <Col xs={24} xl={9}>
          <Card title={t('admin.llm.presets')}>
            {(presets.data || []).map((p) => (
              <Card key={p.id} size="small" hoverable style={{ marginBottom: 8 }}
                onClick={() => form.setFieldsValue({ provider: 'openai', base_url: p.base_url, model: p.model, vision_model: p.vision_model, embed_model: p.embed_model })}>
                <b>{p.title}</b>
                <div className="small muted">{p.base_url} · {p.model || '—'}</div>
                <Typography.Text code className="small">{p.hint}</Typography.Text>
              </Card>
            ))}
          </Card>
        </Col>
      </Row>
    </>
  )
}
