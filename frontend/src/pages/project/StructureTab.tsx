import {
  ApartmentOutlined, CameraOutlined, DeleteOutlined, DownloadOutlined, FileZipOutlined, PlusOutlined,
  ReloadOutlined, SaveOutlined, SubnodeOutlined,
} from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert, Badge, Button, Card, Checkbox, Col, Descriptions, Divider, Empty, Form, Image, Input, List, Modal, Radio,
  Row, Segmented, Select, Space, Spin, Tag, Tooltip, Typography, Upload, App as AntApp,
} from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, download } from '../../api/client'
import type { DiffNode, OrgFunction, OrgUnit, StructureResp } from '../../api/types'
import { canEdit, useAuth } from '../../auth/AuthContext'
import { UnitStatusTag } from '../../components/common'
import { useOpenSource } from '../../components/DocumentViewer'
import OrgChart, { Legend, type ChartLink } from '../../components/org/OrgChart'

const UNIT_TYPES = ['department', 'directorate', 'division', 'service', 'block', 'center', 'sector', 'group', 'direction', 'office', 'branch', 'unit']
const uid = () => `m${Math.random().toString(36).slice(2, 8)}`

function descendants(units: OrgUnit[], id: string): Set<string> {
  const out = new Set<string>()
  const walk = (p: string) => units.filter((u) => u.parent_id === p).forEach((u) => { out.add(u.id); walk(u.id) })
  walk(id)
  return out
}

// ------------------------------------------------------------------ распознавание схемы

function RecognizeModal({ projectId, side, open, onClose, onApply }: {
  projectId: number; side: 'before' | 'after'; open: boolean; onClose: () => void
  onApply: (units: OrgUnit[], mode: 'replace' | 'merge') => void
}) {
  const { t } = useTranslation()
  const { message } = AntApp.useApp()
  const [mode, setMode] = useState('auto')
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState<{ units: OrgUnit[]; preview: string; warnings: string[]; method: string } | null>(null)
  const [apply, setApply] = useState<'replace' | 'merge'>('replace')
  useEffect(() => { if (!open) setRes(null) }, [open])

  const run = async (file: File) => {
    const form = new FormData()
    form.append('file', file)
    form.append('mode', mode)
    setBusy(true)
    try {
      setRes(await api(`/projects/${projectId}/structures/${side}/recognize`, { form }))
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setBusy(false)
    }
  }
  const setName = (id: string, name: string) =>
    setRes((r) => r && { ...r, units: r.units.map((u) => (u.id === id ? { ...u, name } : u)) })
  const setParent = (id: string, parent_id: string | null) =>
    setRes((r) => r && { ...r, units: r.units.map((u) => (u.id === id ? { ...u, parent_id } : u)) })
  const remove = (id: string) =>
    setRes((r) => r && { ...r, units: r.units.filter((u) => u.id !== id).map((u) => (u.parent_id === id ? { ...u, parent_id: null } : u)) })

  return (
    <Modal open={open} onCancel={onClose} width={1200} title={<Space><CameraOutlined />{t('structure.recognize.title')}</Space>}
      okText={t('structure.recognize.apply', { side: t(`structure.${side}`) })} okButtonProps={{ disabled: !res?.units.length }}
      onOk={() => { if (res) { onApply(res.units, apply); onClose() } }}>
      {!res ? (
        <Spin spinning={busy} tip={t('structure.recognize.running')}>
          <Space direction="vertical" style={{ width: '100%' }}>
            <Space>
              <span>{t('structure.recognize.mode')}:</span>
              <Radio.Group value={mode} onChange={(e) => setMode(e.target.value)} optionType="button"
                options={[{ value: 'auto', label: t('structure.recognize.auto') }, { value: 'cv', label: t('structure.recognize.cv') },
                  { value: 'vision', label: t('structure.recognize.vision') }]} />
            </Space>
            <Upload.Dragger accept=".png,.jpg,.jpeg,.pdf,.bmp,.tif,.tiff,.webp" showUploadList={false}
              beforeUpload={(f) => { run(f as unknown as File); return false }}>
              <p className="ant-upload-drag-icon"><ApartmentOutlined /></p>
              <p className="ant-upload-text">{t('structure.recognize.upload')}</p>
              <p className="ant-upload-hint">PNG, JPG, PDF</p>
            </Upload.Dragger>
          </Space>
        </Spin>
      ) : (
        <Row gutter={16}>
          <Col span={11}>
            <Typography.Title level={5}>{t('structure.recognize.original')}</Typography.Title>
            <Image src={res.preview} style={{ maxHeight: 520, objectFit: 'contain', border: '1px solid #e5e7eb' }} />
          </Col>
          <Col span={13}>
            <Typography.Title level={5}>{t('structure.recognize.result')}</Typography.Title>
            <Space wrap style={{ marginBottom: 8 }}>
              <Tag color="blue">{t('structure.recognize.found', { n: res.units.length })}</Tag>
              <Tag>{res.method}</Tag>
              {res.warnings.map((w) => <Tag color="orange" key={w}>{w}</Tag>)}
            </Space>
            <div style={{ maxHeight: 440, overflow: 'auto' }}>
              {res.units.map((u) => (
                <Space key={u.id} style={{ display: 'flex', marginBottom: 6 }} align="start">
                  <Input value={u.name} onChange={(e) => setName(u.id, e.target.value)} style={{ width: 330 }} />
                  <Select allowClear style={{ width: 230 }} value={u.parent_id || undefined} placeholder={t('structure.unit.noParent')}
                    onChange={(v) => setParent(u.id, v || null)}
                    options={res.units.filter((x) => x.id !== u.id).map((x) => ({ value: x.id, label: x.name }))} />
                  <Button danger type="text" icon={<DeleteOutlined />} onClick={() => remove(u.id)} />
                </Space>
              ))}
            </div>
            <Divider style={{ margin: '12px 0' }} />
            <Radio.Group value={apply} onChange={(e) => setApply(e.target.value)}>
              <Radio value="replace">{t('structure.recognize.replace')}</Radio>
              <Radio value="merge">{t('structure.recognize.merge')}</Radio>
            </Radio.Group>
            <Typography.Paragraph type="secondary" className="small" style={{ marginTop: 8 }}>{t('structure.recognize.hint')}</Typography.Paragraph>
          </Col>
        </Row>
      )}
    </Modal>
  )
}

// ------------------------------------------------------------------ пакет документов

function PackageModal({ projectId, side, units, open, onClose, editable }: {
  projectId: number; side: 'before' | 'after'; units: OrgUnit[]; open: boolean; onClose: () => void; editable: boolean
}) {
  const { t } = useTranslation()
  const { message } = AntApp.useApp()
  const qc = useQueryClient()
  const [langs, setLangs] = useState<string[]>(['ru', 'kz'])
  const [unitIds, setUnitIds] = useState<string[]>([])
  const [sources, setSources] = useState(true)
  const [busy, setBusy] = useState(false)
  const [previewUnit, setPreviewUnit] = useState<string | undefined>(units[0]?.id)
  const [previewLang, setPreviewLang] = useState('ru')
  const [html, setHtml] = useState('')
  const files = useQuery({ queryKey: ['files', projectId], queryFn: () => api<any[]>(`/projects/${projectId}/files`), enabled: open })

  useEffect(() => { if (open && !previewUnit && units[0]) setPreviewUnit(units[0].id) }, [open, units, previewUnit])
  useEffect(() => {
    if (!open || !previewUnit) return
    api<{ html: string }>(`/projects/${projectId}/structures/${side}/preview`, { body: { unit_id: previewUnit, lang: previewLang, include_sources: sources } })
      .then((r) => setHtml(r.html)).catch(() => setHtml(''))
  }, [open, previewUnit, previewLang, sources, projectId, side])

  const generate = async () => {
    setBusy(true)
    try {
      const r = await api<{ id: number; filename: string }>(`/projects/${projectId}/structures/${side}/package`, {
        body: { langs, unit_ids: unitIds.length ? unitIds : null, include_sources: sources },
      })
      message.success(t('structure.package.done'))
      qc.invalidateQueries({ queryKey: ['files', projectId] })
      await download(`/files/${r.id}`, r.filename)
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal open={open} onCancel={onClose} width={1200} footer={null} title={<Space><FileZipOutlined />{t('structure.package.title')}</Space>}>
      <Row gutter={20}>
        <Col span={9}>
          <Alert type="info" showIcon message={t('structure.package.contents')} style={{ marginBottom: 12 }} />
          {!editable && <Alert type="warning" showIcon message={t('structure.package.viewOnly')} style={{ marginBottom: 12 }} />}
          <Form layout="vertical">
            {editable && <>
            <Form.Item label={t('structure.package.langs')}>
              <Checkbox.Group value={langs} onChange={(v) => setLangs(v as string[])}
                options={[{ value: 'ru', label: 'Русский' }, { value: 'kz', label: 'Қазақша' }]} />
            </Form.Item>
            <Form.Item label={t('structure.package.units')}>
              <Select mode="multiple" allowClear value={unitIds} onChange={setUnitIds}
                options={units.map((u) => ({ value: u.id, label: u.short ? `${u.name} (${u.short})` : u.name }))} />
            </Form.Item>
            </>}
            <Form.Item>
              <Checkbox checked={sources} onChange={(e) => setSources(e.target.checked)}>{t('structure.package.sources')}</Checkbox>
            </Form.Item>
            <Typography.Paragraph type="secondary" className="small">{t('structure.package.kzNote')}</Typography.Paragraph>
            {editable && (
              <Button type="primary" icon={<FileZipOutlined />} loading={busy} disabled={!langs.length} onClick={generate} block>
                {t('structure.package.generate')}
              </Button>
            )}
          </Form>
          <Divider orientation="left" plain>{t('structure.package.files')}</Divider>
          <List size="small" dataSource={(files.data || []).slice(0, 6)} locale={{ emptyText: t('common.none') }}
            renderItem={(f: any) => (
              <List.Item actions={[<Button key="d" size="small" icon={<DownloadOutlined />} onClick={() => download(`/files/${f.id}`, f.filename)} />]}>
                <Typography.Text ellipsis style={{ maxWidth: 260 }}>{f.filename}</Typography.Text>
              </List.Item>
            )} />
        </Col>
        <Col span={15}>
          <Space style={{ marginBottom: 8 }} wrap>
            <span>{t('structure.package.preview')}:</span>
            <Select style={{ width: 360 }} value={previewUnit} onChange={setPreviewUnit}
              options={units.map((u) => ({ value: u.id, label: u.short ? `${u.name} (${u.short})` : u.name }))} />
            <Segmented value={previewLang} onChange={(v) => setPreviewLang(v as string)} options={[{ value: 'ru', label: 'РУС' }, { value: 'kz', label: 'ҚАЗ' }]} />
          </Space>
          <div style={{ maxHeight: 560, overflow: 'auto' }} dangerouslySetInnerHTML={{ __html: html }} />
        </Col>
      </Row>
    </Modal>
  )
}

// ------------------------------------------------------------------ редактор одной стороны

function UnitPanel({ unit, units, editable, onChange, onDelete, onAddChild }: {
  unit: OrgUnit; units: OrgUnit[]; editable: boolean; onChange: (u: OrgUnit) => void; onDelete: () => void; onAddChild: () => void
}) {
  const { t } = useTranslation()
  const open = useOpenSource()
  const [newFn, setNewFn] = useState('')
  const [newPos, setNewPos] = useState('')
  const blocked = descendants(units, unit.id)
  const set = (patch: Partial<OrgUnit>) => onChange({ ...unit, ...patch })
  return (
    <Card size="small" title={<Typography.Text strong ellipsis style={{ maxWidth: 330 }}>{unit.name}</Typography.Text>}
      extra={editable && (
        <Space>
          <Tooltip title={t('structure.addChild')}><Button size="small" icon={<SubnodeOutlined />} onClick={onAddChild} /></Tooltip>
          <Tooltip title={t('structure.deleteUnit')}><Button size="small" danger icon={<DeleteOutlined />} onClick={onDelete} /></Tooltip>
        </Space>
      )}
      styles={{ body: { maxHeight: 620, overflow: 'auto' } }}>
      <Form layout="vertical" size="small" disabled={!editable}>
        <Form.Item label={t('structure.unit.name')}>
          <Input.TextArea autoSize value={unit.name} onChange={(e) => set({ name: e.target.value })} />
        </Form.Item>
        <Row gutter={8}>
          <Col span={10}>
            <Form.Item label={t('structure.unit.short')}>
              <Input value={unit.short} onChange={(e) => set({ short: e.target.value })} />
            </Form.Item>
          </Col>
          <Col span={14}>
            <Form.Item label={t('structure.unit.type')}>
              <Select value={unit.type} onChange={(v) => set({ type: v })}
                options={UNIT_TYPES.map((x) => ({ value: x, label: t(`unitTypes.${x}`) }))} />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item label={t('structure.unit.parent')}>
          <Select allowClear showSearch optionFilterProp="label" value={unit.parent_id || undefined}
            placeholder={t('structure.unit.noParent')} onChange={(v) => set({ parent_id: v || null })}
            options={units.filter((u) => u.id !== unit.id && !blocked.has(u.id)).map((u) => ({ value: u.id, label: u.name }))} />
        </Form.Item>
        <Form.Item label={t('structure.unit.head')}>
          <Input value={unit.head_title} onChange={(e) => set({ head_title: e.target.value })} />
        </Form.Item>
      </Form>
      <Divider orientation="left" plain style={{ margin: '8px 0' }}>
        {t('structure.functions')} <Badge count={unit.functions.length} color="#1d4ed8" />
      </Divider>
      <List size="small" dataSource={unit.functions}
        renderItem={(f: OrgFunction, i) => (
          <List.Item style={{ padding: '6px 0' }}
            actions={editable ? [<Button key="x" type="text" size="small" danger icon={<DeleteOutlined />}
              onClick={() => set({ functions: unit.functions.filter((_, j) => j !== i) })} />] : []}>
            <div>
              <div style={{ fontSize: 13 }}>{f.text}</div>
              <Space size={4} wrap>
                <Tag bordered={false}>{t(`kinds.${f.kind}`, f.kind)}</Tag>
                {f.shared && <Tag color="purple" bordered={false}>{t('structure.shared')}</Tag>}
                {f.ref_display && f.doc_id && (
                  <a className="small" onClick={() => open({ docId: f.doc_id!, clauseId: f.clause_id })}>
                    {f.doc_title ? `${f.doc_title}, ` : ''}{f.ref_display}
                  </a>
                )}
              </Space>
            </div>
          </List.Item>
        )} />
      {editable && (
        <Space.Compact style={{ width: '100%', marginTop: 6 }}>
          <Input placeholder={t('structure.fnPh')} value={newFn} onChange={(e) => setNewFn(e.target.value)}
            onPressEnter={() => { if (newFn.trim()) { set({ functions: [...unit.functions, { id: '', text: newFn.trim(), kind: 'function' }] }); setNewFn('') } }} />
          <Button icon={<PlusOutlined />} onClick={() => { if (newFn.trim()) { set({ functions: [...unit.functions, { id: '', text: newFn.trim(), kind: 'function' }] }); setNewFn('') } }} />
        </Space.Compact>
      )}
      <Divider orientation="left" plain style={{ margin: '12px 0 8px' }}>{t('structure.positions')}</Divider>
      <Space wrap size={[4, 4]}>
        {unit.positions.map((p, i) => (
          <Tag key={i} closable={editable} onClose={() => set({ positions: unit.positions.filter((_, j) => j !== i) })}>{p.title}</Tag>
        ))}
      </Space>
      {editable && (
        <Space.Compact style={{ width: '100%', marginTop: 6 }}>
          <Input placeholder={t('structure.posPh')} value={newPos} onChange={(e) => setNewPos(e.target.value)}
            onPressEnter={() => { if (newPos.trim()) { set({ positions: [...unit.positions, { title: newPos.trim() }] }); setNewPos('') } }} />
          <Button icon={<PlusOutlined />} onClick={() => { if (newPos.trim()) { set({ positions: [...unit.positions, { title: newPos.trim() }] }); setNewPos('') } }} />
        </Space.Compact>
      )}
    </Card>
  )
}

function SideEditor({ projectId, side }: { projectId: number; side: 'before' | 'after' }) {
  const { t } = useTranslation()
  const { user } = useAuth()
  const editable = canEdit(user)
  const qc = useQueryClient()
  const { message, modal } = AntApp.useApp()
  const q = useQuery({ queryKey: ['structure', projectId, side], queryFn: () => api<StructureResp>(`/projects/${projectId}/structures/${side}`) })
  const [units, setUnits] = useState<OrgUnit[]>([])
  const [dirty, setDirty] = useState(false)
  const [sel, setSel] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [recOpen, setRecOpen] = useState(false)
  const [pkgOpen, setPkgOpen] = useState(false)

  useEffect(() => {
    if (q.data) {
      setUnits(q.data.data.units || [])
      setDirty(false)
    }
  }, [q.data])
  useEffect(() => {
    const h = (e: BeforeUnloadEvent) => { if (dirty) { e.preventDefault(); e.returnValue = '' } }
    window.addEventListener('beforeunload', h)
    return () => window.removeEventListener('beforeunload', h)
  }, [dirty])

  const update = (next: OrgUnit[]) => { setUnits(next); setDirty(true) }
  const selected = units.find((u) => u.id === sel) || null
  const nodes = useMemo(() => units.map((u) => ({
    id: u.id, name: u.name, short: u.short, parent_id: u.parent_id, functions: u.functions.length, head_title: u.head_title,
  })), [units])

  const save = async () => {
    setSaving(true)
    try {
      await api(`/projects/${projectId}/structures/${side}`, { method: 'PUT', body: { units } })
      message.success(t('structure.saved'))
      setDirty(false)
      qc.invalidateQueries({ queryKey: ['structure', projectId, side] })
      qc.invalidateQueries({ queryKey: ['structure-diff', projectId] })
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setSaving(false)
    }
  }
  const rebuild = () => modal.confirm({
    title: t('structure.rebuild'), content: t('structure.rebuildConfirm'),
    onOk: async () => {
      await api(`/projects/${projectId}/structures/${side}/rebuild`, { method: 'POST' })
      qc.invalidateQueries({ queryKey: ['structure', projectId, side] })
    },
  })
  const addUnit = (parent: string | null) => {
    const u: OrgUnit = { id: uid(), name: t('structure.addRoot'), short: '', type: 'unit', parent_id: parent, head_title: '', functions: [], positions: [], origin: 'manual' }
    update([...units, u])
    setSel(u.id)
  }
  const removeUnit = (id: string) => modal.confirm({
    title: t('structure.deleteUnit'), content: t('structure.deleteUnitConfirm'), okButtonProps: { danger: true },
    onOk: () => {
      const target = units.find((u) => u.id === id)
      update(units.filter((u) => u.id !== id).map((u) => (u.parent_id === id ? { ...u, parent_id: target?.parent_id || null } : u)))
      setSel(null)
    },
  })
  const reparent = (child: string, parent: string) => {
    if (child === parent || descendants(units, child).has(parent)) return
    update(units.map((u) => (u.id === child ? { ...u, parent_id: parent } : u)))
  }
  const applyRecognized = (rec: OrgUnit[], mode: 'replace' | 'merge') => {
    const prefixed = rec.map((u) => ({ ...u, id: `r${u.id}`, parent_id: u.parent_id ? `r${u.parent_id}` : null, short: u.short || '', head_title: '', functions: [], positions: [] }))
    if (mode === 'replace') update(prefixed)
    else {
      const names = new Set(units.map((u) => u.name.toLowerCase()))
      update([...units, ...prefixed.filter((u) => !names.has(u.name.toLowerCase()))])
    }
  }

  if (q.isLoading) return <Spin />
  const source = q.data?.source
  return (
    <>
      <Space style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between' }} wrap>
        <Space wrap>
          <Tag color={source === 'manual' ? 'purple' : source === 'import' ? 'cyan' : 'default'}>
            {source === 'manual' ? t('structure.sourceManual') : source === 'import' ? t('structure.sourceImport') : t('structure.sourceAuto')}
          </Tag>
          {dirty && <Tag color="orange">{t('structure.unsaved')}</Tag>}
          <span className="small muted">{t('structure.dragHint')}</span>
        </Space>
        <Space wrap>
          {editable && <Button icon={<PlusOutlined />} onClick={() => addUnit(null)}>{t('structure.addRoot')}</Button>}
          {editable && <Button icon={<CameraOutlined />} onClick={() => setRecOpen(true)}>{t('structure.importChart')}</Button>}
          {editable && <Button icon={<ReloadOutlined />} onClick={rebuild}>{t('structure.rebuild')}</Button>}
          <Button icon={<DownloadOutlined />} onClick={() => download(`/projects/${projectId}/structures/${side}/chart.png`, `chart_${side}.png`)}>{t('structure.exportPng')}</Button>
          <Button icon={<FileZipOutlined />} onClick={() => setPkgOpen(true)} disabled={!units.length || dirty}>
            {editable ? t('structure.generate') : t('structure.package.title')}
          </Button>
          {editable && <Button type="primary" icon={<SaveOutlined />} disabled={!dirty} loading={saving} onClick={save}>{t('structure.save')}</Button>}
        </Space>
      </Space>
      {!units.length ? (
        <Card><Empty description={t('structure.empty')}>{editable && <Button icon={<CameraOutlined />} onClick={() => setRecOpen(true)}>{t('structure.importChart')}</Button>}</Empty></Card>
      ) : (
        <Row gutter={16}>
          <Col xs={24} xl={16}>
            <OrgChart nodes={nodes} selectedId={sel} onSelect={setSel} onReparent={editable ? reparent : undefined} height={660} />
          </Col>
          <Col xs={24} xl={8}>
            {selected ? (
              <UnitPanel unit={selected} units={units} editable={editable}
                onChange={(u) => update(units.map((x) => (x.id === u.id ? u : x)))}
                onDelete={() => removeUnit(selected.id)} onAddChild={() => addUnit(selected.id)} />
            ) : (
              <Card><Empty image={<ApartmentOutlined style={{ fontSize: 48, color: '#cbd5e1' }} />} description={t('structure.select')} /></Card>
            )}
          </Col>
        </Row>
      )}
      <RecognizeModal projectId={projectId} side={side} open={recOpen} onClose={() => setRecOpen(false)} onApply={applyRecognized} />
      <PackageModal projectId={projectId} side={side} units={units} open={pkgOpen} onClose={() => setPkgOpen(false)}
        editable={editable} />
    </>
  )
}

// ------------------------------------------------------------------ схема изменений

export function DiffView({ projectId, height = 640 }: { projectId: number; height?: number }) {
  const { t } = useTranslation()
  const q = useQuery({ queryKey: ['structure-diff', projectId], queryFn: () => api<{ nodes: DiffNode[]; links: ChartLink[] }>(`/projects/${projectId}/structure-diff`) })
  const [sel, setSel] = useState<string | null>(null)
  if (q.isLoading) return <Spin />
  if (!q.data?.nodes.length) return <Empty description={t('structure.diffEmpty')} />
  const node = q.data.nodes.find((n) => n.id === sel)
  const counts = q.data.nodes.reduce<Record<string, number>>((a, n) => ({ ...a, [n.status]: (a[n.status] || 0) + 1 }), {})
  return (
    <Row gutter={16}>
      <Col xs={24} xl={17}>
        <Space style={{ marginBottom: 8 }} wrap>
          <Legend />
          {Object.entries(counts).map(([s, n]) => <span key={s}><UnitStatusTag s={s} />{n}</span>)}
        </Space>
        <OrgChart nodes={q.data.nodes} links={q.data.links} selectedId={sel} onSelect={setSel} height={height} />
      </Col>
      <Col xs={24} xl={7}>
        {node ? (
          <Card size="small" title={node.name}>
            <Descriptions size="small" column={1}>
              <Descriptions.Item label={t('common.status')}><UnitStatusTag s={node.status} /></Descriptions.Item>
              {node.short && <Descriptions.Item label={t('structure.unit.short')}>{node.short}</Descriptions.Item>}
              {node.before_name && node.before_name !== node.name && <Descriptions.Item label={t('structure.before')}>{node.before_name}</Descriptions.Item>}
              <Descriptions.Item label={t('structure.functions')}>{node.functions}</Descriptions.Item>
              {!!node.lost && <Descriptions.Item label={t('analysis.unitCols.lost')}><Tag color="red">{node.lost}</Tag></Descriptions.Item>}
              {!!node.sources?.length && <Descriptions.Item label={t('structure.from', { src: '' })}>{node.sources.join(', ')}</Descriptions.Item>}
            </Descriptions>
            {!!node.destinations?.length && (
              <>
                <Divider plain orientation="left">{t('analysis.unitCols.dest')}</Divider>
                {node.destinations.map((d) => <div key={d.unit} className="small">{d.unit} — {d.count}</div>)}
              </>
            )}
          </Card>
        ) : (
          <Alert type="info" showIcon message={t('structure.select')} />
        )}
      </Col>
    </Row>
  )
}

export default function StructureTab({ projectId }: { projectId: number }) {
  const { t } = useTranslation()
  const [view, setView] = useState<'before' | 'after' | 'changes'>('after')
  return (
    <>
      <Segmented style={{ marginBottom: 16 }} value={view} onChange={(v) => setView(v as any)}
        options={[
          { value: 'before', label: t('structure.before') },
          { value: 'after', label: t('structure.after') },
          { value: 'changes', label: t('structure.changes') },
        ]} />
      {view === 'changes' ? <DiffView projectId={projectId} /> : <SideEditor key={view} projectId={projectId} side={view} />}
    </>
  )
}
