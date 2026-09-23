import { ApartmentOutlined, CheckCircleFilled, CloseCircleFilled, ExperimentOutlined, RobotOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { Segmented, Tag, Tooltip } from 'antd'
import { useTranslation } from 'react-i18next'
import { api } from '../api/client'
import type { Meta, Severity } from '../api/types'
import { setLang } from '../i18n'

export const useMeta = () => useQuery({ queryKey: ['meta'], queryFn: () => api<Meta>('/meta'), staleTime: 30_000 })

export function Brand({ admin = false, collapsed = false }: { admin?: boolean; collapsed?: boolean }) {
  const { t } = useTranslation()
  return (
    <div className={`brand ${admin ? 'admin' : ''}`}>
      <span className="logo">
        <ApartmentOutlined />
      </span>
      {!collapsed && <span>{t('app.title')}</span>}
    </div>
  )
}

export function LangSwitch({ size = 'middle' }: { size?: 'small' | 'middle' }) {
  const { i18n } = useTranslation()
  return (
    <Segmented
      size={size}
      value={i18n.language}
      onChange={(v) => setLang(v as 'ru' | 'kz')}
      options={[
        { label: 'РУС', value: 'ru' },
        { label: 'ҚАЗ', value: 'kz' },
      ]}
    />
  )
}

export function AiBadge() {
  const { t } = useTranslation()
  const { data } = useMeta()
  if (!data) return null
  const on = data.llm.enabled
  return (
    <Tooltip title={on ? t('ai.onHint') : t('ai.demoHint')}>
      <Tag icon={on ? <RobotOutlined /> : <ExperimentOutlined />} color={on ? 'green' : 'default'} style={{ marginInlineEnd: 0 }}>
        {on ? t('ai.on', { model: data.llm.model }) : t('ai.demo')}
      </Tag>
    </Tooltip>
  )
}

const SEV_COLORS: Record<Severity, string> = { high: 'red', medium: 'orange', low: 'blue', info: 'default' }
export function SeverityTag({ s }: { s: Severity }) {
  const { t } = useTranslation()
  return <Tag color={SEV_COLORS[s]}>{t(`severity.${s}`)}</Tag>
}

export const UNIT_STATUS_COLORS: Record<string, string> = {
  preserved: 'default', renamed: 'blue', reorganized: 'orange', split: 'orange', merged: 'green', created: 'green', abolished: 'red',
}
export function UnitStatusTag({ s }: { s: string }) {
  const { t } = useTranslation()
  return <Tag color={UNIT_STATUS_COLORS[s] || 'default'}>{t(`unitStatus.${s}`, s)}</Tag>
}

export const FN_STATUS_COLORS: Record<string, string> = {
  preserved: 'default', transferred: 'gold', modified: 'lime', lost: 'red', relocated: 'purple', new: 'green',
}
export function FnStatusTag({ s }: { s: string }) {
  const { t } = useTranslation()
  return <Tag color={FN_STATUS_COLORS[s] || 'default'}>{t(`fnStatus.${s}`, s)}</Tag>
}

export function ReviewIcon({ s }: { s?: string }) {
  if (s === 'confirmed') return <CheckCircleFilled style={{ color: '#16a34a' }} />
  if (s === 'rejected') return <CloseCircleFilled style={{ color: '#dc2626' }} />
  return null
}

export function sideColor(side: string) {
  return ({ before: 'orange', after: 'green', requirements: 'purple', benchmark: 'cyan' } as Record<string, string>)[side] || 'default'
}

export function fmtSize(n: number) {
  if (n > 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} МБ`
  return `${Math.max(1, Math.round(n / 1024))} КБ`
}
