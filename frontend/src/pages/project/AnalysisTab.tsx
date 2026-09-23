import {
  CheckOutlined, CloseOutlined, ExperimentOutlined, LoadingOutlined, MinusCircleOutlined, RobotOutlined,
  ThunderboltOutlined, WarningOutlined,
} from '@ant-design/icons'
import { useQueryClient } from '@tanstack/react-query'
import {
  Alert, Button, Card, Checkbox, Col, Collapse, Empty, Input, Progress, Result, Row, Segmented, Select, Space,
  Statistic, Steps, Switch, Table, Tabs, Tag, Tooltip, Typography, App as AntApp,
} from 'antd'
import dayjs from 'dayjs'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../../api/client'
import type { Finding, FnMapRow, Run, TraceStep, UnitStatus } from '../../api/types'
import { canEdit, useAuth } from '../../auth/AuthContext'
import { FnStatusTag, ReviewIcon, SeverityTag, UnitStatusTag, useMeta } from '../../components/common'
import { EvidenceItem } from '../../components/DocumentViewer'
import { useLatestRun } from '../ProjectPage'
import { DiffView } from './StructureTab'

export function AgentTrace({ trace, compact = false }: { trace: TraceStep[]; compact?: boolean }) {
  const { t } = useTranslation()
  const icon = (s: TraceStep['status']) =>
    s === 'running' ? <LoadingOutlined /> : s === 'skipped' ? <MinusCircleOutlined style={{ color: '#9ca3af' }} /> :
      s === 'error' ? <WarningOutlined style={{ color: '#dc2626' }} /> : undefined
  const status = (s: TraceStep['status']) => (s === 'done' ? 'finish' : s === 'running' ? 'process' : s === 'error' ? 'error' : 'wait')
  return (
    <Steps
      className="agent-trace"
      direction="vertical"
      size="small"
      items={trace.map((s) => ({
        title: <Space>{s.title}{s.duration !== undefined && <span className="small muted">{s.duration} с</span>}
          {s.status === 'skipped' && <Tag>{t('common.none')}</Tag>}</Space>,
        status: status(s.status) as any,
        icon: icon(s.status),
        description: (
          <div>
            {s.summary && <div>{s.summary}</div>}
            {!compact && s.log?.length > 0 && (
              <Collapse ghost size="small" items={[{ key: '1', label: <span className="small muted">log ({s.log.length})</span>,
                children: <pre style={{ fontSize: 11, whiteSpace: 'pre-wrap', margin: 0 }}>{s.log.join('\n')}</pre> }]} />
            )}
          </div>
        ),
      }))}
    />
  )
}

function FindingCard({ f, runId, editable }: { f: Finding; runId: number; editable: boolean }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const { message } = AntApp.useApp()
  const [comment, setComment] = useState(f.review?.comment || '')
  const [busy, setBusy] = useState(false)
  const review = async (status: string) => {
    setBusy(true)
    try {
      await api(`/analysis/${runId}/findings/${f.id}/review`, { method: 'PUT', body: { status, comment } })
      qc.invalidateQueries({ queryKey: ['latest-run'] })
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setBusy(false)
    }
  }
  const rs = f.review?.status || 'pending'
  return (
    <Card size="small" className={`finding-card sev-${f.severity} ${rs === 'rejected' ? 'rejected' : ''}`} style={{ marginBottom: 12 }}
      title={
        <Space wrap size={6}>
          <Typography.Text type="secondary">{f.id}</Typography.Text>
          <SeverityTag s={f.severity} />
          <Tag bordered={false}>{t(`findingType.${f.type}`)}</Tag>
          {f.method === 'rules+llm' && <Tag icon={<RobotOutlined />} color={f.disputed ? 'orange' : 'green'}>{f.disputed ? t('analysis.disputed') : 'ИИ ✓'}</Tag>}
          {f.inherited !== undefined && <Tag bordered={false}>{f.inherited ? t('analysis.inherited') : t('analysis.newDup')}</Tag>}
          <ReviewIcon s={rs} />
        </Space>
      }
      extra={<Tooltip title={t('analysis.confidence')}><Progress type="circle" size={30} percent={Math.round(f.confidence * 100)} /></Tooltip>}>
      <Typography.Paragraph strong style={{ marginBottom: 6 }}>{f.title}</Typography.Paragraph>
      <Typography.Paragraph style={{ marginBottom: 6 }}>{f.description}</Typography.Paragraph>
      {f.units.length > 0 && <Space wrap size={[4, 4]} style={{ marginBottom: 4 }}>{f.units.map((u) => <Tag key={u} color="geekblue">{u}</Tag>)}</Space>}
      <div className="small muted" style={{ marginTop: 6 }}>{t('analysis.evidence')}:</div>
      {f.evidence.map((e, i) => <EvidenceItem key={i} e={e} />)}
      {f.recommendation && (
        <Alert type="info" showIcon style={{ marginTop: 10 }} message={t('analysis.recommendation')} description={f.recommendation} />
      )}
      {f.llm_note && (
        <Alert type={f.disputed ? 'warning' : 'success'} showIcon icon={<RobotOutlined />} style={{ marginTop: 8 }}
          message={t('analysis.llmNote')} description={f.llm_note} />
      )}
      <Space style={{ marginTop: 10, width: '100%' }} wrap>
        {editable ? (
          <>
            <Input size="small" placeholder={t('analysis.comment')} value={comment} onChange={(e) => setComment(e.target.value)} style={{ width: 320 }} />
            <Button size="small" icon={<CheckOutlined />} type={rs === 'confirmed' ? 'primary' : 'default'} loading={busy}
              onClick={() => review(rs === 'confirmed' ? 'pending' : 'confirmed')}>{t('analysis.confirm')}</Button>
            <Button size="small" icon={<CloseOutlined />} danger={rs === 'rejected'} type={rs === 'rejected' ? 'primary' : 'default'} loading={busy}
              onClick={() => review(rs === 'rejected' ? 'pending' : 'rejected')}>{t('analysis.reject')}</Button>
          </>
        ) : (
          <Tag>{t(`review.${rs}`)}</Tag>
        )}
        {f.review?.reviewer && <span className="small muted">{t('analysis.reviewed', { who: f.review.reviewer })}{f.review.comment ? ` — «${f.review.comment}»` : ''}</span>}
      </Space>
    </Card>
  )
}

function Findings({ run, editable }: { run: Run; editable: boolean }) {
  const { t } = useTranslation()
  const findings = run.result!.findings
  const [type, setType] = useState<string>('all')
  const [sev, setSev] = useState<string[]>([])
  const [rev, setRev] = useState<string>('all')
  const [q, setQ] = useState('')
  const [hideInfo, setHideInfo] = useState(false)
  const types = ['loss', 'duplication', 'conflict', 'reorganization', 'requirement_gap', 'benchmark', 'improvement']
    .filter((x) => findings.some((f) => f.type === x))
  const list = findings.filter((f) =>
    (type === 'all' || f.type === type) && (!sev.length || sev.includes(f.severity)) &&
    (rev === 'all' || (f.review?.status || 'pending') === rev) && (!hideInfo || f.severity !== 'info') &&
    (!q || (f.title + f.description + f.units.join(' ')).toLowerCase().includes(q.toLowerCase())))
  return (
    <>
      <Space wrap style={{ marginBottom: 12 }}>
        <Segmented value={type} onChange={(v) => setType(v as string)}
          options={[{ value: 'all', label: `${t('common.all')} (${findings.length})` },
            ...types.map((x) => ({ value: x, label: `${t(`findingType.${x}`)} (${findings.filter((f) => f.type === x).length})` }))]} />
        <Select mode="multiple" allowClear placeholder={t('analysis.filters.severity')} style={{ minWidth: 180 }} value={sev} onChange={setSev}
          options={['high', 'medium', 'low', 'info'].map((s) => ({ value: s, label: t(`severity.${s}`) }))} />
        <Select value={rev} onChange={setRev} style={{ width: 170 }}
          options={[{ value: 'all', label: `${t('analysis.filters.review')}: ${t('common.all')}` },
            ...['pending', 'confirmed', 'rejected'].map((s) => ({ value: s, label: t(`review.${s}`) }))]} />
        <Input.Search allowClear placeholder={t('analysis.filters.search')} onChange={(e) => setQ(e.target.value)} style={{ width: 240 }} />
        <Checkbox checked={hideInfo} onChange={(e) => setHideInfo(e.target.checked)}>{t('analysis.filters.hideInfo')}</Checkbox>
      </Space>
      {list.length ? list.map((f) => <FindingCard key={f.id} f={f} runId={run.id} editable={editable} />) : <Empty />}
    </>
  )
}

function UnitsTable({ units }: { units: UnitStatus[] }) {
  const { t } = useTranslation()
  const label = (u: { name: string; short: string }) => (u.short ? `${u.name} (${u.short})` : u.name)
  return (
    <Table size="small" rowKey="key" dataSource={units} pagination={false}
      columns={[
        { title: t('analysis.unitCols.status'), dataIndex: 'status', width: 140, render: (s) => <UnitStatusTag s={s} />,
          filters: [...new Set(units.map((u) => u.status))].map((s) => ({ text: t(`unitStatus.${s}`), value: s })),
          onFilter: (v, r) => r.status === v },
        { title: t('analysis.unitCols.before'), render: (_, r) => (r.before ? label(r.before) : '—') },
        { title: t('analysis.unitCols.after'), render: (_, r) => (r.before ? r.after.map(label).join(', ') || '—' : `${r.after.map(label).join(', ')}${r.sources?.length ? `  ← ${r.sources.join(', ')}` : ''}`) },
        { title: t('analysis.unitCols.coverage'), dataIndex: 'coverage', width: 120, render: (c) => (c === null || c === undefined ? '—' : <Progress percent={Math.round(c * 100)} size="small" />) },
        { title: t('analysis.unitCols.lost'), dataIndex: 'functions_lost', width: 90, render: (n, r) => (n ? <Tag color="red">{n} / {r.functions_total}</Tag> : '—') },
        { title: t('analysis.unitCols.dest'), render: (_, r) => r.destinations?.slice(0, 4).map((d) => <div key={d.unit} className="small">{d.unit} — {d.count}</div>) },
      ]} />
  )
}

function MappingTable({ rows }: { rows: FnMapRow[] }) {
  const { t } = useTranslation()
  const [status, setStatus] = useState<string>('changed')
  const [q, setQ] = useState('')
  const data = rows.filter((r) => (status === 'all' || (status === 'changed' ? r.status !== 'preserved' : r.status === status)) &&
    (!q || `${r.before?.text || ''} ${r.after.map((a) => a.text).join(' ')} ${r.before?.unit || ''}`.toLowerCase().includes(q.toLowerCase())))
  const counts = rows.reduce<Record<string, number>>((a, r) => ({ ...a, [r.status]: (a[r.status] || 0) + 1 }), {})
  return (
    <>
      <Space wrap style={{ marginBottom: 12 }}>
        <Segmented value={status} onChange={(v) => setStatus(v as string)}
          options={[{ value: 'changed', label: `≠ (${rows.length - (counts.preserved || 0)})` }, { value: 'all', label: `${t('common.all')} (${rows.length})` },
            ...['lost', 'transferred', 'modified', 'new', 'relocated', 'preserved'].filter((s) => counts[s]).map((s) => ({ value: s, label: `${t(`fnStatus.${s}`)} (${counts[s]})` }))]} />
        <Input.Search allowClear placeholder={t('common.search')} onChange={(e) => setQ(e.target.value)} style={{ width: 260 }} />
      </Space>
      <Table size="small" rowKey="id" dataSource={data} pagination={{ pageSize: 25, showSizeChanger: true }}
        columns={[
          { title: t('analysis.mapCols.status'), dataIndex: 'status', width: 150, render: (s, r) => (
            <Space direction="vertical" size={2}>
              <FnStatusTag s={s} />
              {r.shared && <Tag bordered={false} color="purple">{t('structure.shared')}</Tag>}
              {r.verified && <Tooltip title={r.verified.reason}><Tag icon={<RobotOutlined />} bordered={false}>{r.verified.verdict}</Tag></Tooltip>}
            </Space>) },
          { title: t('analysis.mapCols.before'), render: (_, r) => r.before ? (
            <div><Tag color="orange" bordered={false}>{r.before.unit}</Tag><EvidenceItem e={r.before} /></div>) : '—' },
          { title: t('analysis.mapCols.after'), render: (_, r) => r.status === 'lost'
            ? (r.after[0] ? <div className="small muted">{t('analysis.nearest')}: <EvidenceItem e={{ ...r.after[0] }} compact /></div> : '—')
            : r.after.slice(0, r.receivers.length > 1 ? 1 : 1).map((a, i) => (
              <div key={i}><Tag color="green" bordered={false}>{r.receivers.length > 1 ? r.receivers.join(', ') : a.unit}</Tag><EvidenceItem e={a} /></div>)) },
          { title: t('analysis.mapCols.score'), dataIndex: 'score', width: 90, sorter: (a, b) => a.score - b.score, render: (s) => `${Math.round(s * 100)}%` },
        ]} />
    </>
  )
}

function Requirements({ run }: { run: Run }) {
  const { t } = useTranslation()
  const req = run.result?.requirements
  if (!req?.items?.length) return <Empty />
  return (
    <Table size="small" rowKey={(r: any) => r.requirement.clause_id + r.requirement.doc_id} dataSource={req.items} pagination={false}
      columns={[
        { title: t('analysis.reqCols.status'), dataIndex: 'status', width: 130, render: (s) => <Tag color={{ covered: 'green', partial: 'gold', gap: 'red' }[s as string]}>{t(`analysis.reqStatus.${s}`)}</Tag> },
        { title: t('analysis.reqCols.requirement'), render: (_, r: any) => <EvidenceItem e={r.requirement} /> },
        { title: t('analysis.reqCols.function'), render: (_, r: any) => <EvidenceItem e={r.function} /> },
      ]} />
  )
}

function Summary({ run }: { run: Run }) {
  const { t } = useTranslation()
  const s = run.result!.summary
  const us = s.units_by_status || {}
  const fs = s.functions_by_status || {}
  const count = (tp: string) => run.result!.findings.filter((f) => f.type === tp && f.review?.status !== 'rejected').length
  return (
    <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
      <Col xs={24} md={8} xl={6}>
        <Card size="small" className="stat-card">
          <Statistic title={t('analysis.cards.units')} value={`${s.units_before} → ${s.units_after}`} />
          <Space wrap size={[4, 4]} style={{ marginTop: 6 }}>
            {(us.created || us.merged) ? <Tag color="green">{t('analysis.cards.created')}: {(us.created || 0) + (us.merged || 0)}</Tag> : null}
            {us.abolished ? <Tag color="red">{t('analysis.cards.abolished')}: {us.abolished}</Tag> : null}
            {(us.reorganized || us.split) ? <Tag color="orange">{t('analysis.cards.reorganized')}: {(us.reorganized || 0) + (us.split || 0)}</Tag> : null}
            {us.renamed ? <Tag color="blue">{t('unitStatus.renamed').toLowerCase()}: {us.renamed}</Tag> : null}
            <Tag>{t('analysis.cards.preserved')}: {us.preserved || 0}</Tag>
          </Space>
        </Card>
      </Col>
      <Col xs={12} md={8} xl={4}><Card size="small" className="stat-card"><Statistic title={t('analysis.cards.lost')} value={count('loss')} valueStyle={{ color: '#dc2626' }} /></Card></Col>
      <Col xs={12} md={8} xl={4}><Card size="small" className="stat-card"><Statistic title={t('analysis.cards.dups')} value={count('duplication')} valueStyle={{ color: '#d97706' }} /></Card></Col>
      <Col xs={12} md={8} xl={4}><Card size="small" className="stat-card"><Statistic title={t('analysis.cards.conflicts')} value={count('conflict')} valueStyle={{ color: '#7c3aed' }} /></Card></Col>
      <Col xs={12} md={8} xl={6}>
        <Card size="small" className="stat-card">
          <Statistic title={t('analysis.cards.functions')} value={`${s.functions_before} → ${s.functions_after}`} />
          <Progress size="small" percent={Math.round((((fs.preserved || 0) + (fs.transferred || 0)) / Math.max(1, s.functions_before)) * 100)}
            format={(p) => `${p}% ${t('analysis.cards.kept')}`} />
        </Card>
      </Col>
    </Row>
  )
}

export default function AnalysisTab({ projectId }: { projectId: number }) {
  const { t } = useTranslation()
  const { user } = useAuth()
  const editable = canEdit(user)
  const meta = useMeta()
  const qc = useQueryClient()
  const { message } = AntApp.useApp()
  const runQ = useLatestRun(projectId)
  const [useLlm, setUseLlm] = useState(true)
  const [useEdited, setUseEdited] = useState(true)
  const [starting, setStarting] = useState(false)
  const run = runQ.data
  const llmOn = !!meta.data?.llm.enabled

  const start = async () => {
    setStarting(true)
    try {
      await api(`/projects/${projectId}/analysis`, { body: { use_llm: useLlm && llmOn, use_edited_structure: useEdited } })
      qc.invalidateQueries({ queryKey: ['latest-run', projectId] })
      qc.invalidateQueries({ queryKey: ['structure-diff', projectId] })
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setStarting(false)
    }
  }

  const controls = editable && (
    <Space wrap>
      <Tooltip title={llmOn ? t('ai.onHint') : t('ai.demoHint')}>
        <Space size={4}><Switch size="small" checked={useLlm && llmOn} disabled={!llmOn} onChange={setUseLlm} />{t('analysis.useLlm')}</Space>
      </Tooltip>
      <Space size={4}><Switch size="small" checked={useEdited} onChange={setUseEdited} />{t('analysis.useEdited')}</Space>
      <Button type="primary" icon={<ThunderboltOutlined />} loading={starting || (!!run && ['pending', 'running'].includes(run.status))} onClick={start}>
        {run ? t('analysis.rerun') : t('analysis.run')}
      </Button>
    </Space>
  )

  const insight = useMemo(() => run?.result, [run])
  if (runQ.isLoading) return <Card loading />
  if (!run) return (
    <Card>
      <Result icon={<ExperimentOutlined style={{ color: '#1d4ed8' }} />} title={t('analysis.noRun')} subTitle={t('analysis.noRunHint')} extra={controls} />
    </Card>
  )
  if (run.status === 'pending' || run.status === 'running') return (
    <Row gutter={16}>
      <Col xs={24} lg={14}>
        <Card title={<Space><LoadingOutlined />{t('analysis.running')}</Space>}>
          <Progress percent={Math.round(run.progress * 100)} status="active" style={{ marginBottom: 16 }} />
          <AgentTrace trace={run.trace} />
        </Card>
      </Col>
    </Row>
  )
  if (run.status === 'error') return (
    <Card>
      <Result status="error" title={t('analysis.error')} subTitle={run.error} extra={controls} />
      <AgentTrace trace={run.trace} />
    </Card>
  )

  return (
    <>
      <div className="page-title">
        <Space wrap>
          <Typography.Text type="secondary">{dayjs(run.finished_at || run.created_at).format('DD.MM.YYYY HH:mm')}</Typography.Text>
          {insight?.llm.enabled ? <Tag icon={<RobotOutlined />} color="green">{t('analysis.llmUsed', { model: insight.llm.model, calls: insight.llm.calls })}</Tag>
            : <Tag icon={<ExperimentOutlined />}>{t('analysis.llmNotUsed')}</Tag>}
        </Space>
        {controls}
      </div>
      <Alert type="warning" showIcon message={t('analysis.disclaimer')} style={{ marginBottom: 12 }} />
      <Summary run={run} />
      <Tabs
        items={[
          { key: 'findings', label: t('analysis.tabs.findings'), children: <Findings run={run} editable={editable} /> },
          { key: 'chart', label: t('analysis.tabs.chart'), children: <DiffView projectId={projectId} /> },
          { key: 'units', label: t('analysis.tabs.units'), children: <UnitsTable units={run.result!.units} /> },
          { key: 'mapping', label: t('analysis.tabs.mapping'), children: <MappingTable rows={run.result!.function_map} /> },
          ...(run.result!.requirements?.items?.length ? [{ key: 'req', label: t('analysis.tabs.requirements'), children: <Requirements run={run} /> }] : []),
          { key: 'trace', label: t('analysis.trace'), children: <Card><AgentTrace trace={run.trace} /></Card> },
        ]}
      />
    </>
  )
}
