export interface Venue {
  id: string
  name: string
  building: string
  level: string
  capacity: number
  stepFree: boolean
  wheelchairSpaces: number
  accessNote: string
  available: boolean
  resources: string[]
}

export interface Need {
  id: string
  name: string
  requirements: string[]
}

export interface Session {
  id: string
  title: string
  start: string
  end: string
  venue: string
  attendeeCount: number
  requiredResources: string[]
  needs: Need[]
}

export interface Violation {
  code: string
  sessionId: string
  sessionTitle: string
  venueId: string | null
  detail: string
  participantId?: string
  requirement?: string
}

export interface Move {
  sessionId: string
  sessionTitle: string
  from: string
  to: string
  toName: string
  attendees: number
  capacity: number
  reason?: string
}

export interface QuickFix {
  rule: string
  moves: Move[]
  violations: Violation[]
  unresolved: number
  looksFine: boolean
}

export interface Incident {
  id: string
  createdAt: string
  venueId: string
  note: string
  source: string
  status: string
}

export interface HistoryRow {
  ra: { id: string; createdAt: string; status: string; engine: string; sandboxId: string; summary: string; moves: Move[]; elapsedMs: number }
  incident: { id: string; note: string; createdAt: string } | null
  venue: string | null
  verification: { id: string; unresolved: number; constraintChecks: number; passed: boolean; createdAt: string; engine: string; sandboxId: string } | null
}

export interface State {
  event: { id: string; name: string; date: string; organiser: string }
  venues: Venue[]
  sessions: Session[]
  participantTotal: number
  requirementHolders: Need[]
  violations: Violation[]
  incident: Incident | null
  quickFix: QuickFix | null
  history: HistoryRow[]
}

export interface Health {
  neo4j: { ok: boolean; version?: string; edition?: string; seeded?: boolean; database?: string; error?: string }
  daytona: { mode: 'daytona' | 'local' | 'unconfigured'; sandboxId: string | null; state: string; detail: string }
  nosana: { enabled: boolean; model: string | null }
}

export interface TraceRow {
  session: string
  title: string
  start: string
  attendees: number
  equipment: string[]
  needs: { id: string; name: string; requirement: string }[]
}

export interface Trace {
  cypher: string
  params: Record<string, string>
  rows: TraceRow[]
  sessions: number
  attendees: number
  requirementHolders: number
}

export interface GraphNode {
  id: string
  kind: string
  label: string
  sub: string
  tone: string
  col: number
}

export interface GraphData {
  nodes: GraphNode[]
  edges: { from: string; to: string; label: string; tone?: string; dashed?: boolean }[]
  columns?: string[]
  cypher?: string
}

export interface Memory {
  priorIncidents: number
  recoveryId: string | null
  at: string | null
  verificationId: string | null
  moves: { session: string; from: string; to: string }[]
  cypher: string
}

export interface RejectedVenue {
  venueId: string
  venueName: string
  reasons: string[]
}

export interface Proposal {
  status: 'feasible' | 'infeasible'
  assignment?: Record<string, string>
  moves?: Move[]
  sessionsMoved?: number
  spareSeats?: number
  violationsAfter?: Violation[]
  disrupted: string[]
  rejectedVenues?: Record<string, RejectedVenue[]>
  blockedSessions?: { sessionId: string; sessionTitle: string; attendees: number; rejectedVenues: RejectedVenue[] }[]
  reason?: string
  precedent?: { moves: Record<string, string>; valid: boolean; violations: string[]; followed?: boolean } | null
  nodesExplored: number
  elapsedMs: number
  runtime?: { python: string; host: string }
}

export interface Execution {
  engine: 'daytona' | 'local'
  sandboxId: string | null
  exitCode: number
  elapsedMs: number
}

export interface Recovery {
  recovery: { id: string; status: string; createdAt: string }
  proposal: Proposal
  execution: Execution
  explanation: { text: string; by: 'nosana' | 'template'; warning?: string }
  memory: Memory | null
}

export interface Verification {
  verification: {
    id: string
    createdAt: string
    unresolved: number
    constraintChecks: number
    passed: boolean
    status: string
    engine: string
    sandboxId: string
    violations: Violation[]
    sessions: number
  }
  execution: Execution
  state: State
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  const text = await res.text()
  let data: unknown = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    throw new Error(res.ok ? 'Invalid response from server' : `Server error ${res.status}: the backend may not be running`)
  }
  if (!res.ok) {
    const detail = (data as { detail?: unknown })?.detail
    throw new Error(typeof detail === 'string' ? detail : `Request failed (${res.status})`)
  }
  return data as T
}

export const api = {
  health: () => call<Health>('GET', '/health'),
  state: () => call<State>('GET', '/state'),
  reset: (full = false) => call<{ seeded: unknown; state: State }>('POST', `/reset${full ? '?full=true' : ''}`),
  memory: (venueId: string) => call<Memory>('GET', `/memory/${venueId}`),
  impact: () => call<GraphData>('GET', '/graph/impact'),
  provenance: (raId: string) => call<GraphData>('GET', `/graph/provenance/${raId}`),
  interpret: (text: string) => call<{ venueId: string | null; summary: string; by: string; warning?: string }>('POST', '/interpret', { text }),
  close: (venueId: string, note: string, source: string) =>
    call<{ incident: Incident; trace: Trace; memory: Memory; state: State }>('POST', `/venues/${venueId}/close`, { note, source }),
  setAvailability: (venueId: string, available: boolean) => call<State>('POST', `/venues/${venueId}/availability`, { available }),
  trace: (venueId: string) => call<Trace>('GET', `/trace/${venueId}`),
  recover: () => call<Recovery>('POST', '/recover'),
  approve: (id: string) => call<Verification>('POST', `/recoveries/${id}/approve`),
}

export const RESOURCE_LABELS: Record<string, string> = {
  projector: 'Projector',
  microphone: 'Mic & PA',
  hearing_loop: 'Hearing loop',
  lecture_capture: 'Lecture capture',
}

export const REQUIREMENT_LABELS: Record<string, string> = {
  step_free: 'Step-free access',
  hearing_loop: 'Hearing loop',
  wheelchair_space: 'Wheelchair space',
}
