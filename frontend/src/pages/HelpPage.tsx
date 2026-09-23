import { ApiOutlined, FileSearchOutlined, InfoCircleOutlined } from '@ant-design/icons'
import { Card, Col, Descriptions, Row, Steps, Tag, Typography } from 'antd'
import { useTranslation } from 'react-i18next'
import { AiBadge, useMeta } from '../components/common'

export default function HelpPage() {
  const { t } = useTranslation()
  const meta = useMeta()
  const steps = t('help.steps', { returnObjects: true }) as string[]
  return (
    <div className="page">
      <div className="page-title"><h2>{t('help.title')}</h2><AiBadge /></div>
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={14}>
          <Card>
            <Steps direction="vertical" current={-1} items={steps.map((s, i) => ({ title: `${i + 1}`, description: s }))} />
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card title={<><ApiOutlined /> {t('help.models')}</>} style={{ marginBottom: 16 }}>
            <Typography.Paragraph>{t('help.modelsText')}</Typography.Paragraph>
            <Typography.Paragraph code>docker compose --profile ollama up -d</Typography.Paragraph>
            <Typography.Paragraph code>LLM_PROVIDER=openai LLM_BASE_URL=http://localhost:11434/v1 LLM_MODEL=qwen2.5:7b-instruct</Typography.Paragraph>
          </Card>
          <Card title={<><FileSearchOutlined /> {t('help.formats')}</>} style={{ marginBottom: 16 }}>
            {meta.data?.formats.map((f) => <Tag key={f}>{f}</Tag>)}
            <Descriptions size="small" column={1} style={{ marginTop: 12 }}>
              <Descriptions.Item label="OCR">{meta.data?.ocr ? <Tag color="green">Tesseract</Tag> : <Tag>{t('ai.ocrOff')}</Tag>}</Descriptions.Item>
              <Descriptions.Item label="PDF">{meta.data?.pdf_export ? <Tag color="green">LibreOffice</Tag> : <Tag>{t('ai.pdfOff')}</Tag>}</Descriptions.Item>
              <Descriptions.Item label="Version">{meta.data?.version}</Descriptions.Item>
            </Descriptions>
          </Card>
          <Card title={<><InfoCircleOutlined /> {t('help.limits')}</>}>
            <Typography.Paragraph>{t('help.limitsText')}</Typography.Paragraph>
          </Card>
        </Col>
      </Row>
    </div>
  )
}
