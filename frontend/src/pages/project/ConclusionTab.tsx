import { FileExcelOutlined, FilePdfOutlined, FileWordOutlined, CodeOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Card, Empty, Segmented, Space, Spin, Tag, Tooltip, Typography, App as AntApp } from 'antd'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, download } from '../../api/client'
import type { Conclusion } from '../../api/types'
import { ReviewIcon, SeverityTag, useMeta } from '../../components/common'
import { useLatestRun } from '../ProjectPage'

export default function ConclusionTab({ projectId }: { projectId: number }) {
  const { t, i18n } = useTranslation()
  const { message } = AntApp.useApp()
  const meta = useMeta()
  const run = useLatestRun(projectId)
  const [lang, setLang] = useState(i18n.language === 'kz' ? 'kz' : 'ru')
  const runId = run.data?.status === 'done' ? run.data.id : null
  const reviewsKey = JSON.stringify(run.data?.result?.findings.map((f) => f.review?.status))
  const concl = useQuery({
    queryKey: ['conclusion', runId, lang, reviewsKey],
    queryFn: () => api<Conclusion>(`/analysis/${runId}/conclusion?lang=${lang}`),
    enabled: !!runId,
  })
  const [busy, setBusy] = useState<string | null>(null)
  const exp = async (kind: string) => {
    setBusy(kind)
    try {
      await download(`/analysis/${runId}/export/${kind}?lang=${lang}`, kind)
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setBusy(null)
    }
  }

  if (!runId) return <Card><Empty description={t('conclusion.empty')} /></Card>
  return (
    <>
      <div className="page-title">
        <Space>
          <span>{t('conclusion.lang')}:</span>
          <Segmented value={lang} onChange={(v) => setLang(v as string)} options={[{ value: 'ru', label: 'Русский' }, { value: 'kz', label: 'Қазақша' }]} />
        </Space>
        <Space wrap>
          <Button icon={<FileWordOutlined />} loading={busy === 'conclusion.docx'} onClick={() => exp('conclusion.docx')}>{t('conclusion.exportDocx')}</Button>
          <Tooltip title={!meta.data?.pdf_export ? t('ai.pdfOff') : undefined}>
            <Button icon={<FilePdfOutlined />} disabled={!meta.data?.pdf_export} loading={busy === 'conclusion.pdf'} onClick={() => exp('conclusion.pdf')}>{t('conclusion.exportPdf')}</Button>
          </Tooltip>
          <Button icon={<FileExcelOutlined />} loading={busy === 'mapping.xlsx'} onClick={() => exp('mapping.xlsx')}>{t('conclusion.exportXlsx')}</Button>
          <Button icon={<CodeOutlined />} loading={busy === 'result.json'} onClick={() => exp('result.json')}>{t('conclusion.exportJson')}</Button>
        </Space>
      </div>
      <Alert type="info" showIcon message={t('conclusion.reviewedNote')} style={{ marginBottom: 12 }} />
      {concl.isLoading || !concl.data ? <Spin /> : (
        <Card className="conclusion" style={{ maxWidth: 1100 }}>
          <Typography.Title level={3} style={{ textAlign: 'center' }}>{concl.data.title}</Typography.Title>
          {concl.data.sections.map((s) => (
            <div key={s.id}>
              <Typography.Title level={4}>{s.title}</Typography.Title>
              {s.paragraphs.filter(Boolean).map((p, i) => <Typography.Paragraph key={i}>{p}</Typography.Paragraph>)}
              {s.method && <Typography.Paragraph type="secondary" italic className="small">{s.method}</Typography.Paragraph>}
              {s.items.map((it, i) => (
                <div className="item" key={i}>
                  <Space align="start">
                    {it.finding_id && <Tag>{it.finding_id}</Tag>}
                    {it.finding_id && <SeverityTag s={it.severity} />}
                    <div>
                      <div>{it.text} <ReviewIcon s={it.review} /></div>
                      {it.sources.map((src, j) => <div key={j} className="src">{t('common.source')}: {src}</div>)}
                    </div>
                  </Space>
                </div>
              ))}
            </div>
          ))}
        </Card>
      )}
    </>
  )
}
