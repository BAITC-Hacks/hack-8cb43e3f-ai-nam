import { DownloadOutlined, FileTextOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { Button, Checkbox, Descriptions, Drawer, Empty, Input, Space, Spin, Tag, Tooltip, Typography } from 'antd'
import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { api, download } from '../api/client'
import type { Clause, DocBrief, Evidence } from '../api/types'
import { sideColor } from './common'

type Target = { docId: number; clauseId?: string } | null
const Ctx = createContext<(t: Target) => void>(() => {})
export const useOpenSource = () => useContext(Ctx)

const FN_KINDS = new Set(['function', 'task', 'duty', 'right'])

export function SourceProvider({ children }: { children: ReactNode }) {
  const [target, setTarget] = useState<Target>(null)
  return (
    <Ctx.Provider value={setTarget}>
      {children}
      <DocumentViewer target={target} onClose={() => setTarget(null)} />
    </Ctx.Provider>
  )
}

function DocumentViewer({ target, onClose }: { target: Target; onClose: () => void }) {
  const { t } = useTranslation()
  const [q, setQ] = useState('')
  const [onlyFn, setOnlyFn] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const doc = useQuery({
    queryKey: ['document', target?.docId],
    queryFn: () => api<DocBrief & { clauses: Clause[] }>(`/documents/${target!.docId}`),
    enabled: !!target,
  })
  useEffect(() => {
    setQ('')
    setOnlyFn(false)
  }, [target?.docId])
  useEffect(() => {
    if (!target?.clauseId || !doc.data) return
    const el = document.getElementById(`cl-${target.clauseId}`)
    if (el) setTimeout(() => el.scrollIntoView({ behavior: 'smooth', block: 'center' }), 150)
  }, [target?.clauseId, doc.data])
  const clauses = useMemo(() => {
    const all = doc.data?.clauses || []
    return all.filter((c) => (!onlyFn || FN_KINDS.has(c.kind)) && (!q || c.text.toLowerCase().includes(q.toLowerCase()) || c.ref.includes(q)))
  }, [doc.data, q, onlyFn])

  return (
    <Drawer open={!!target} onClose={onClose} width={Math.min(900, window.innerWidth - 40)}
      title={<Space><FileTextOutlined />{doc.data?.title || t('documents.viewer')}</Space>}
      extra={doc.data && (
        <Button icon={<DownloadOutlined />} onClick={() => download(`/documents/${doc.data!.id}/file`, doc.data!.filename)}>
          {t('common.download')}
        </Button>
      )}>
      {doc.isLoading ? <Spin /> : !doc.data ? <Empty /> : (
        <>
          <Descriptions size="small" column={2} style={{ marginBottom: 12 }}>
            <Descriptions.Item label={t('common.source')}>{doc.data.filename}</Descriptions.Item>
            <Descriptions.Item label={t('common.status')}><Tag color={sideColor(doc.data.side)}>{t(`sides.${doc.data.side}`)}</Tag></Descriptions.Item>
            {doc.data.edition && <Descriptions.Item label="Ред.">№ {doc.data.edition}</Descriptions.Item>}
            {doc.data.approval && <Descriptions.Item label="">{doc.data.approval}</Descriptions.Item>}
          </Descriptions>
          <Space style={{ marginBottom: 8 }} wrap>
            <Input.Search allowClear placeholder={t('common.search')} onChange={(e) => setQ(e.target.value)} style={{ width: 300 }} />
            <Checkbox checked={onlyFn} onChange={(e) => setOnlyFn(e.target.checked)}>{t('documents.onlyFunctions')}</Checkbox>
          </Space>
          <div ref={box}>
            {clauses.map((c) => (
              <div key={c.id} id={`cl-${c.id}`}
                className={`clause ${c.is_heading ? 'heading' : ''} ${target?.clauseId === c.id ? 'hl' : ''}`}
                style={{ marginLeft: Math.min(4, Math.max(0, c.level - 1)) * 14 }}>
                <span className="num">{c.ref_display}</span>
                {c.text}
                {!c.is_heading && FN_KINDS.has(c.kind) && (
                  <Tooltip title={c.actor ? `${t('documents.actor')}: ${c.actor}` : undefined}>
                    <Tag className="kind" bordered={false} color="blue">{t(`kinds.${c.kind}`, c.kind)}</Tag>
                  </Tooltip>
                )}
                {c.page && <Typography.Text type="secondary" className="small"> · {t('documents.pages')} {c.page}</Typography.Text>}
              </div>
            ))}
          </div>
        </>
      )}
    </Drawer>
  )
}

export function EvidenceItem({ e, compact = false }: { e: Evidence; compact?: boolean }) {
  const { t } = useTranslation()
  const open = useOpenSource()
  return (
    <div className={`evidence ${e.side}`} onClick={() => e.doc_id && open({ docId: e.doc_id, clauseId: e.clause_id })}>
      <Space size={6} wrap>
        <Tag color={sideColor(e.side)} style={{ marginInlineEnd: 0 }}>{t(`sides.short.${e.side}`, e.side)}</Tag>
        <span className="ref">{e.ref_display}</span>
        <span className="muted small">{e.doc_title}{e.page ? `, ${t('documents.pages')} ${e.page}` : ''}</span>
        {e.unit && <Tag bordered={false}>{e.unit}</Tag>}
        {e.role === 'nearest' && <Tag bordered={false} color="default">{t('analysis.nearest')}</Tag>}
        {typeof e.score === 'number' && <span className="small muted">{Math.round(e.score * 100)}%</span>}
      </Space>
      {!compact && <div className="quote">«{e.text}»</div>}
    </div>
  )
}
