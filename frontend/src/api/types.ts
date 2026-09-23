export type Role = 'admin' | 'analyst' | 'viewer'
export type Side = 'before' | 'after' | 'requirements' | 'benchmark'
export type Severity = 'high' | 'medium' | 'low' | 'info'

export interface User {
  id: number
  email: string
  full_name: string
  role: Role
  is_active: boolean
  language: string
  must_change_password: boolean
  created_at?: string
  last_login_at?: string | null
}

export interface Meta {
  app_name: string
  version: string
  llm: { enabled: boolean; model: string; vision: boolean; embeddings: boolean; provider: string }
  ocr: boolean
  pdf_export: boolean
  formats: string[]
  demo_available: boolean
  max_upload_mb: number
}

export interface Project {
  id: number
  name: string
  description: string
  status: string
  is_demo: boolean
  owner: string
  created_at: string
  updated_at: string
  documents: Record<Side, number>
  last_run: null | {
    id: number
    status: string
    progress: number
    created_at: string
    lost?: number
    duplicates?: number
    conflicts?: number
    findings?: number
    units_by_status?: Record<string, number>
  }
}

export interface DocBrief {
  id: number
  side: Side
  filename: string
  title: string
  doc_kind: string
  status: 'uploaded' | 'processing' | 'parsed' | 'error'
  error: string
  method: string
  pages: number
  clause_count: number
  size: number
  edition: string
  approval: string
  warnings: string[]
  abbreviations: number
  has_orgchart: boolean
}

export interface Clause {
  id: string
  ref: string
  ref_display: string
  text: string
  level: number
  kind: string
  parent: string | null
  section: string
  context: string
  actor: string
  page: number | null
  is_heading: boolean
}

export interface Evidence {
  side: string
  doc_id: number
  doc_title: string
  clause_id: string
  ref?: string
  ref_display: string
  page?: number | null
  text: string
  score?: number
  unit?: string
  role?: string
}

export interface Finding {
  id: string
  type: 'loss' | 'duplication' | 'conflict' | 'reorganization' | 'improvement' | 'requirement_gap' | 'benchmark'
  subtype?: string
  severity: Severity
  title: string
  description: string
  units: string[]
  evidence: Evidence[]
  recommendation: string
  confidence: number
  method: string
  llm_note?: string
  disputed?: boolean
  inherited?: boolean
  review?: { status: 'pending' | 'confirmed' | 'rejected'; comment: string; reviewer?: string; updated_at?: string }
}

export interface UnitRef {
  id: string
  name: string
  short: string
  type?: string
  functions: number
  head_title?: string
}

export interface UnitStatus {
  key: string
  status: string
  before: null | (UnitRef & { parent: string })
  after: UnitRef[]
  coverage: number | null
  functions_total: number
  functions_lost?: number
  destinations?: { unit: string; count: number }[]
  sources?: string[]
  finding_id?: string
}

export interface FnMapRow {
  id: string
  status: 'preserved' | 'transferred' | 'modified' | 'lost' | 'relocated' | 'new'
  score: number
  generic: boolean
  shared: boolean
  before: (Evidence & { unit: string; unit_id: string }) | null
  after: (Evidence & { unit: string; unit_id: string })[]
  receivers: string[]
  verified: null | { verdict: string; reason: string; by: string }
  finding_id?: string
}

export interface TraceStep {
  step: string
  title: string
  status: 'pending' | 'running' | 'done' | 'skipped' | 'error'
  summary: string
  log: string[]
  duration?: number
}

export interface ConclusionItem {
  finding_id: string | null
  severity: Severity
  text: string
  sources: string[]
  review: string
  disputed?: boolean
}

export interface Conclusion {
  title: string
  lang: string
  generated_at: string
  summary_method: string
  sections: { id: string; title: string; paragraphs: string[]; items: ConclusionItem[]; method?: string }[]
}

export interface AnalysisResult {
  summary: Record<string, any>
  units: UnitStatus[]
  function_map: FnMapRow[]
  findings: Finding[]
  recommendations: { finding_id: string; text: string; severity: Severity; units: string[] }[]
  conclusion: Conclusion
  requirements?: { items: any[]; covered: number; partial: number; gaps: number }
  benchmark?: { items: any[] }
  documents: { id: number; side: string; filename: string; title: string; edition?: string }[]
  llm: { enabled: boolean; model: string; calls: number; errors: number; seconds: number; embeddings: boolean }
}

export interface Run {
  id: number
  project_id: number
  status: 'pending' | 'running' | 'done' | 'error'
  progress: number
  current_step: string
  llm_model: string
  error: string
  created_at: string
  finished_at: string | null
  summary: Record<string, any>
  trace: TraceStep[]
  result?: AnalysisResult
}

export interface OrgFunction {
  id: string
  text: string
  kind: string
  doc_id?: number | null
  doc_title?: string
  clause_id?: string
  ref_display?: string
  shared?: boolean
  match_text?: string
}

export interface OrgUnit {
  id: string
  name: string
  short: string
  type: string
  parent_id: string | null
  head_title: string
  origin?: string
  functions: OrgFunction[]
  positions: { title: string; count?: number | null }[]
  evidence?: Evidence[]
  bbox?: number[]
}

export interface StructureResp {
  side: 'before' | 'after'
  source: string
  data: { units: OrgUnit[]; unassigned?: OrgFunction[] }
  updated_at: string | null
}

export interface DiffNode {
  id: string
  name: string
  short: string
  type: string
  parent_id: string | null
  status: string
  functions: number
  head_title?: string
  lost?: number
  sources?: string[]
  before_name?: string
  finding_id?: string
  destinations?: { unit: string; count: number }[]
}
