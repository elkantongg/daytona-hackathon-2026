<script setup lang="ts">
import { computed } from 'vue'
import type { GraphData } from '../api'

const props = defineProps<{ graph: GraphData }>()

const W = 1320
const BOX_W = 160
const BOX_H = 54
const ROW_GAP = 26
const TOP = 34

const layout = computed(() => {
  const cols = Math.max(props.graph.columns?.length || 0, ...props.graph.nodes.map((n) => n.col + 1))
  const byCol: Record<number, typeof props.graph.nodes> = {}
  for (const n of props.graph.nodes) (byCol[n.col] ||= []).push(n)
  const tallest = Math.max(1, ...Object.values(byCol).map((c) => c.length))
  const height = TOP + tallest * (BOX_H + ROW_GAP) + 10
  const step = cols > 1 ? (W - BOX_W - 10) / (cols - 1) : 0
  const pos: Record<string, { x: number; y: number }> = {}
  for (const [c, list] of Object.entries(byCol)) {
    const colH = list.length * (BOX_H + ROW_GAP) - ROW_GAP
    const y0 = TOP + (height - TOP - 10 - colH) / 2
    list.forEach((n, i) => (pos[n.id] = { x: 5 + Number(c) * step, y: y0 + i * (BOX_H + ROW_GAP) }))
  }
  const headers = (props.graph.columns || []).map((label, i) => ({ label, x: 5 + i * step + BOX_W / 2 }))
  const edges = props.graph.edges
    .filter((e) => pos[e.from] && pos[e.to])
    .map((e) => {
      const a = pos[e.from]
      const b = pos[e.to]
      const forward = a.x <= b.x
      const x1 = forward ? a.x + BOX_W : a.x
      const x2 = forward ? b.x : b.x + BOX_W
      const y1 = a.y + BOX_H / 2
      const y2 = b.y + BOX_H / 2
      const dx = Math.max(30, Math.abs(x2 - x1) / 2) * (forward ? 1 : -1)
      const d = `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`
      // Label sits mid-gap; converging edges arrive at different heights so labels stay apart.
      const t = 0.5
      const lx = (1 - t) ** 3 * x1 + 3 * (1 - t) ** 2 * t * (x1 + dx) + 3 * (1 - t) * t ** 2 * (x2 - dx) + t ** 3 * x2
      const ly = (1 - t) ** 3 * y1 + 3 * (1 - t) ** 2 * t * y1 + 3 * (1 - t) * t ** 2 * y2 + t ** 3 * y2
      return { ...e, d, lx, ly }
    })
  return { height, pos, headers, edges }
})

function trunc(s: string, n: number) {
  return s.length > n ? s.slice(0, n - 1) + '…' : s
}
</script>

<template>
  <svg :viewBox="`0 0 ${W} ${layout.height}`" class="graph" role="img" aria-label="Graph view">
    <defs>
      <marker v-for="t in ['', 'go', 'bad', 'info']" :id="`arrow-${t || 'n'}`" :key="t" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M0,0 L10,5 L0,10 z" :class="`fill-${t || 'n'}`" />
      </marker>
    </defs>

    <text v-for="h in layout.headers" :key="h.label" :x="h.x" y="14" class="colhead" text-anchor="middle">{{ h.label.toUpperCase() }}</text>

    <g v-for="(e, i) in layout.edges" :key="i" :class="['edge', e.tone || 'n', { dashed: e.dashed }]">
      <path :d="e.d" :marker-end="`url(#arrow-${e.tone || 'n'})`" />
      <g :transform="`translate(${e.lx},${e.ly})`">
        <rect :x="-(e.label.length * 3.4 + 6)" y="-9" :width="e.label.length * 6.8 + 12" height="18" rx="4" class="lbg" />
        <text text-anchor="middle" y="4" class="elabel">{{ e.label }}</text>
      </g>
    </g>

    <g v-for="n in graph.nodes" :key="n.id" :transform="`translate(${layout.pos[n.id].x},${layout.pos[n.id].y})`" :class="['node', n.tone || 'n']">
      <title>{{ n.kind }}: {{ n.label }}{{ n.sub ? ' (' + n.sub + ')' : '' }}</title>
      <rect :width="BOX_W" :height="BOX_H" rx="10" />
      <text x="10" y="16" class="kind">:{{ n.kind }}</text>
      <text x="10" y="34" class="label">{{ trunc(n.label, 20) }}</text>
      <text x="10" y="48" class="sub">{{ trunc(n.sub || "", 28) }}</text>
    </g>
  </svg>
</template>

<style scoped>
.graph { width: 100%; height: auto; display: block; font-family: var(--sans); }
.colhead { fill: var(--faint); font-size: 10px; letter-spacing: .1em; font-weight: 600; }
.node rect { fill: #17201b; stroke: #36493d; stroke-width: 1.2; }
.node.go rect { fill: #1b2a12; stroke: var(--go); }
.node.bad rect { fill: #2e1913; stroke: var(--bad); }
.node.info rect { fill: #142534; stroke: var(--info); }
.kind { font-family: var(--mono); font-size: 9.5px; fill: var(--faint); }
.label { font-size: 14px; font-weight: 600; fill: var(--text); }
.sub { font-size: 10px; fill: var(--muted); }
.edge path { fill: none; stroke: #4a5b51; stroke-width: 1.4; }
.edge.go path { stroke: var(--go); }
.edge.bad path { stroke: var(--bad); }
.edge.info path { stroke: var(--info); }
.edge.dashed path { stroke-dasharray: 5 4; }
.lbg { fill: #0b0f0d; stroke: var(--line); }
.elabel { font-family: var(--mono); font-size: 11px; fill: var(--muted); }
.edge.go .elabel { fill: var(--go); }
.edge.bad .elabel { fill: var(--bad); }
.edge.info .elabel { fill: var(--info); }
.fill-n { fill: #4a5b51; }
.fill-go { fill: var(--go); }
.fill-bad { fill: var(--bad); }
.fill-info { fill: var(--info); }
</style>
