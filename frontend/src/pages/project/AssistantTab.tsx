import { ClearOutlined, RobotOutlined, SendOutlined, UserOutlined } from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Avatar, Button, Card, Col, Empty, Input, List, Row, Space, Tag, Typography, App as AntApp } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../../api/client'
import { useOpenSource } from '../../components/DocumentViewer'
import { sideColor } from '../../components/common'

interface Msg { id: number; role: 'user' | 'assistant'; content: string; sources: any[]; meta: any }

export default function AssistantTab({ projectId }: { projectId: number }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const { message } = AntApp.useApp()
  const open = useOpenSource()
  const hist = useQuery({ queryKey: ['chat', projectId], queryFn: () => api<Msg[]>(`/projects/${projectId}/chat`) })
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [pending, setPending] = useState<string | null>(null)
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth' }) }, [hist.data, pending])

  const ask = async (q: string) => {
    if (!q.trim()) return
    setBusy(true)
    setPending(q)
    setText('')
    try {
      await api(`/projects/${projectId}/chat`, { body: { message: q } })
      await qc.invalidateQueries({ queryKey: ['chat', projectId] })
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setBusy(false)
      setPending(null)
    }
  }
  const renderText = (m: Msg) => {
    const parts = m.content.split(/(\[S\d+\])/g)
    return parts.map((p, i) => {
      const mm = /\[(S\d+)\]/.exec(p)
      if (!mm) return <span key={i}>{p}</span>
      const src = m.sources.find((s) => s.sid === mm[1])
      return (
        <Tag key={i} color="blue" style={{ cursor: 'pointer', marginInline: 2 }}
          onClick={() => src?.doc_id && open({ docId: src.doc_id, clauseId: src.clause_id })}>{mm[1]}</Tag>
      )
    })
  }
  const examples = [t('assistant.ex1'), t('assistant.ex2'), t('assistant.ex3'), t('assistant.ex4')]
  const msgs = hist.data || []

  return (
    <Row gutter={16}>
      <Col xs={24} lg={17}>
        <Card title={<Space><RobotOutlined />{t('assistant.title')}</Space>}
          extra={<Button icon={<ClearOutlined />} size="small" onClick={async () => { await api(`/projects/${projectId}/chat`, { method: 'DELETE' }); qc.invalidateQueries({ queryKey: ['chat', projectId] }) }}>{t('assistant.clear')}</Button>}>
          <div style={{ minHeight: 360, maxHeight: 560, overflow: 'auto', padding: 4, background: '#f8fafc', borderRadius: 8 }}>
            {!msgs.length && !pending && <Empty style={{ marginTop: 80 }} description={t('assistant.empty')} />}
            {msgs.map((m) => (
              <div key={m.id}>
                <div className={`chat-msg ${m.role}`}>
                  <Space align="start">
                    <Avatar size="small" icon={m.role === 'user' ? <UserOutlined /> : <RobotOutlined />}
                      style={{ background: m.role === 'user' ? '#1e40af' : '#16a34a' }} />
                    <div>{m.role === 'assistant' ? renderText(m) : m.content}</div>
                  </Space>
                  {m.role === 'assistant' && (
                    <div style={{ marginTop: 6 }}>
                      <Tag bordered={false}>{m.meta?.mode === 'llm' ? t('assistant.modeLlm') : t('assistant.modeRetrieval')}</Tag>
                    </div>
                  )}
                </div>
                {m.role === 'assistant' && m.sources?.length > 0 && (
                  <List size="small" style={{ maxWidth: 860, marginBottom: 8 }} dataSource={m.sources}
                    renderItem={(s: any) => (
                      <List.Item style={{ cursor: s.doc_id ? 'pointer' : 'default', padding: '4px 8px' }}
                        onClick={() => s.doc_id && open({ docId: s.doc_id, clauseId: s.clause_id })}>
                        <Space size={6} wrap>
                          <Tag color="blue">{s.sid}</Tag>
                          {s.side && <Tag color={sideColor(s.side)}>{t(`sides.short.${s.side}`)}</Tag>}
                          <Typography.Text type="secondary" className="small">{s.doc_title}, {s.ref_display}</Typography.Text>
                          <Typography.Text className="small" ellipsis style={{ maxWidth: 520 }}>{s.text}</Typography.Text>
                        </Space>
                      </List.Item>
                    )} />
                )}
              </div>
            ))}
            {pending && <div className="chat-msg user">{pending}</div>}
            {pending && <div className="chat-msg assistant"><RobotOutlined spin /> …</div>}
            <div ref={end} />
          </div>
          <Space.Compact style={{ width: '100%', marginTop: 12 }}>
            <Input.TextArea autoSize={{ minRows: 1, maxRows: 4 }} value={text} onChange={(e) => setText(e.target.value)}
              placeholder={t('assistant.placeholder')} onPressEnter={(e) => { if (!e.shiftKey) { e.preventDefault(); ask(text) } }} />
            <Button type="primary" icon={<SendOutlined />} loading={busy} onClick={() => ask(text)}>{t('assistant.send')}</Button>
          </Space.Compact>
        </Card>
      </Col>
      <Col xs={24} lg={7}>
        <Card size="small" title={t('assistant.examples')}>
          <Space direction="vertical" style={{ width: '100%' }}>
            {examples.map((e) => <Button key={e} block style={{ textAlign: 'left', whiteSpace: 'normal', height: 'auto' }} onClick={() => ask(e)} disabled={busy}>{e}</Button>)}
          </Space>
        </Card>
      </Col>
    </Row>
  )
}
