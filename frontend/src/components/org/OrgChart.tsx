import dagre from '@dagrejs/dagre'
import {
  Background, Controls, Handle, MarkerType, MiniMap, Position, ReactFlow, ReactFlowProvider, applyNodeChanges,
  useReactFlow, type Edge, type Node, type NodeChange, type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Tag, Tooltip } from 'antd'
import { memo, useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

export interface ChartNode {
  id: string
  name: string
  short?: string
  parent_id: string | null
  status?: string
  functions?: number
  head_title?: string
  type?: string
  lost?: number
  badge?: string
}

export interface ChartLink {
  from: string
  to: string
  kind?: string
}

const W = 240
const H = 92

function layout(nodes: ChartNode[], direction: 'TB' | 'LR') {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: direction, nodesep: 28, ranksep: 64, marginx: 20, marginy: 20 })
  g.setDefaultEdgeLabel(() => ({}))
  const ids = new Set(nodes.map((n) => n.id))
  nodes.forEach((n) => g.setNode(n.id, { width: W, height: H }))
  nodes.forEach((n) => {
    if (n.parent_id && ids.has(n.parent_id)) g.setEdge(n.parent_id, n.id)
  })
  dagre.layout(g)
  const pos: Record<string, { x: number; y: number }> = {}
  nodes.forEach((n) => {
    const p = g.node(n.id)
    pos[n.id] = { x: (p?.x ?? 0) - W / 2, y: (p?.y ?? 0) - H / 2 }
  })
  return pos
}

type OrgNodeData = Record<string, unknown> & ChartNode & { selected?: boolean; dropTarget?: boolean; direction: 'TB' | 'LR' }

const OrgNode = memo(({ data }: NodeProps<Node<OrgNodeData>>) => {
  const { t } = useTranslation()
  const vertical = data.direction === 'TB'
  return (
    <div className={`org-node st-${data.status || 'none'} ${data.selected ? 'selected' : ''} ${data.dropTarget ? 'drop-target' : ''}`}>
      <Handle type="target" position={vertical ? Position.Top : Position.Left} style={{ opacity: 0 }} />
      <Tooltip title={data.name} mouseEnterDelay={0.6}>
        <div className="title clamp-2">{data.name}</div>
      </Tooltip>
      <div className="meta">
        {data.short && <Tag bordered={false} style={{ marginInlineEnd: 0 }}>{data.short}</Tag>}
        {typeof data.functions === 'number' && <span>{data.functions} {t('structure.fns')}</span>}
        {data.status && data.status !== 'preserved' && data.status !== 'none' && (
          <Tag color={{ created: 'green', merged: 'green', abolished: 'red', reorganized: 'orange', split: 'orange', renamed: 'blue' }[data.status] || 'default'}
            style={{ marginInlineEnd: 0 }}>
            {t(`unitStatus.${data.status}`, data.status)}
          </Tag>
        )}
        {!!data.lost && <Tag color="red" bordered={false} style={{ marginInlineEnd: 0 }}>{t('structure.lost', { n: data.lost })}</Tag>}
      </div>
      {data.head_title && <div className="meta small">{data.head_title}</div>}
      <Handle type="source" position={vertical ? Position.Bottom : Position.Right} style={{ opacity: 0 }} />
    </div>
  )
})

const nodeTypes = { org: OrgNode }

interface Props {
  nodes: ChartNode[]
  links?: ChartLink[]
  selectedId?: string | null
  onSelect?: (id: string | null) => void
  onReparent?: (childId: string, newParentId: string) => void
  height?: number | string
  direction?: 'TB' | 'LR'
}

function Chart({ nodes, links = [], selectedId, onSelect, onReparent, height = 560, direction = 'TB' }: Props) {
  const rf = useReactFlow()
  const [dropTarget, setDropTarget] = useState<string | null>(null)
  const positions = useMemo(() => layout(nodes, direction), [nodes, direction])
  const computed: Node<OrgNodeData>[] = useMemo(
    () => nodes.map((n) => ({
      id: n.id,
      type: 'org',
      position: positions[n.id] || { x: 0, y: 0 },
      data: { ...n, selected: n.id === selectedId, dropTarget: n.id === dropTarget, direction },
      draggable: !!onReparent,
    })),
    [nodes, positions, selectedId, dropTarget, onReparent, direction],
  )
  // Контролируемые узлы: изменения (в т.ч. измеренные размеры) применяются через applyNodeChanges
  const [rfNodes, setRfNodes] = useState<Node<OrgNodeData>[]>([])
  useEffect(() => {
    setRfNodes((prev) => computed.map((n) => {
      const old = prev.find((o) => o.id === n.id)
      return old?.dragging ? { ...n, position: old.position, dragging: true, measured: old.measured } : { ...n, measured: old?.measured }
    }))
  }, [computed])
  const onNodesChange = useCallback((changes: NodeChange<Node<OrgNodeData>>[]) => {
    setRfNodes((nds) => applyNodeChanges(changes, nds))
  }, [])
  const rfEdges: Edge[] = useMemo(() => {
    const ids = new Set(nodes.map((n) => n.id))
    const tree: Edge[] = nodes
      .filter((n) => n.parent_id && ids.has(n.parent_id))
      .map((n) => ({
        id: `e-${n.parent_id}-${n.id}`, source: n.parent_id!, target: n.id, type: 'smoothstep',
        style: { stroke: n.status === 'abolished' ? '#dc2626' : '#94a3b8', strokeWidth: 1.6,
          strokeDasharray: n.status === 'abolished' ? '6 4' : undefined },
      }))
    const extra: Edge[] = links.filter((l) => ids.has(l.from) && ids.has(l.to)).map((l) => ({
      id: `l-${l.from}-${l.to}`, source: l.from, target: l.to, type: 'default', animated: true,
      style: { stroke: '#d97706', strokeWidth: 1.4, strokeDasharray: '5 5' },
      markerEnd: { type: MarkerType.ArrowClosed, color: '#d97706' },
    }))
    return [...tree, ...extra]
  }, [nodes, links])

  useEffect(() => {
    const tm = setTimeout(() => rf.fitView({ padding: 0.12, duration: 300, maxZoom: 1.1 }), 120)
    return () => clearTimeout(tm)
  }, [nodes.length, direction, rf])

  const onNodeDrag = useCallback((_: unknown, node: Node) => {
    const hits = rf.getIntersectingNodes(node).filter((n) => n.id !== node.id)
    setDropTarget(hits[0]?.id || null)
  }, [rf])

  const onNodeDragStop = useCallback((_: unknown, node: Node) => {
    const hits = rf.getIntersectingNodes(node).filter((n) => n.id !== node.id)
    setDropTarget(null)
    if (hits[0] && onReparent) onReparent(node.id, hits[0].id)
    else setRfNodes((nds) => nds.map((n) => (n.id === node.id ? { ...n, position: positions[n.id] || n.position } : n)))
  }, [rf, onReparent, positions])

  // высота области подстраивается под пропорции дерева (широкие неглубокие схемы не оставляют пустоты)
  const autoHeight = useMemo(() => {
    const ps = Object.values(positions)
    if (!ps.length || typeof height !== 'number') return height
    const w = Math.max(...ps.map((p) => p.x)) - Math.min(...ps.map((p) => p.x)) + W + 40
    const h = Math.max(...ps.map((p) => p.y)) - Math.min(...ps.map((p) => p.y)) + H + 40
    const zoom = Math.min(1.1, 950 / w)
    return Math.max(340, Math.min(height, Math.round(h * zoom + 90)))
  }, [positions, height])

  return (
    <div style={{ height: autoHeight, background: '#f8fafc', borderRadius: 10, border: '1px solid #e5e7eb' }}>
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        nodeTypes={nodeTypes}
        onNodeClick={(_, n) => onSelect?.(n.id)}
        onPaneClick={() => onSelect?.(null)}
        onNodeDrag={onReparent ? onNodeDrag : undefined}
        onNodeDragStop={onReparent ? onNodeDragStop : undefined}
        onNodesChange={onNodesChange}
        nodesConnectable={false}
        minZoom={0.15}
        fitView
        fitViewOptions={{ padding: 0.12, maxZoom: 1.1 }}
      >
        <Background gap={20} color="#e2e8f0" />
        {nodes.length > 12 && <MiniMap pannable zoomable nodeColor={(n) => ({ created: '#86efac', merged: '#86efac', abolished: '#fca5a5', reorganized: '#fcd34d', split: '#fcd34d', renamed: '#93c5fd' } as Record<string, string>)[(n.data as any)?.status] || '#cbd5e1'} />}
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  )
}

export default function OrgChart(props: Props) {
  return (
    <ReactFlowProvider>
      <Chart {...props} />
    </ReactFlowProvider>
  )
}

export function Legend() {
  const { t } = useTranslation()
  const items: [string, string, string][] = [
    ['created', '#16a34a', '#f0fdf4'], ['renamed', '#2563eb', '#eff6ff'], ['reorganized', '#d97706', '#fffbeb'],
    ['abolished', '#dc2626', '#fef2f2'], ['preserved', '#cbd5e1', '#ffffff'],
  ]
  return (
    <div className="legend">
      {items.map(([k, b, f]) => (
        <span key={k}><span className="sw" style={{ borderColor: b, background: f, borderStyle: k === 'abolished' ? 'dashed' : 'solid' }} />{t(`unitStatus.${k}`)}</span>
      ))}
      <span><span className="sw" style={{ borderColor: '#d97706', borderStyle: 'dashed', background: 'transparent', width: 22, borderWidth: '2px 0 0 0' }} />{t('structure.successors')}</span>
    </div>
  )
}
