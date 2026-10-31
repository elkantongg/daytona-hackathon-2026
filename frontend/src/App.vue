<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import ScheduleBoard from './components/ScheduleBoard.vue'
import GraphView from './components/GraphView.vue'
import { api, REQUIREMENT_LABELS } from './api'
import type { GraphData, Health, Memory, Recovery, State, Trace, Verification, Violation } from './api'

type View = 'live' | 'quickfix' | 'proposal' | 'impact' | 'provenance'

const health = ref<Health | null>(null)
const state = ref<State | null>(null)
const trace = ref<Trace | null>(null)
const recovery = ref<Recovery | null>(null)
const verification = ref<Verification | null>(null)
const impact = ref<GraphData | null>(null)
const provenance = ref<GraphData | null>(null)
const memory = ref<Memory | null>(null)
const showGraphCypher = ref(false)
const staleNote = ref('')
const busy = ref<string | null>(null)
const error = ref('')
const view = ref<View>('live')
const report = ref('Lecture Theatre 1 has a burst pipe; facilities have closed it for the morning.')
const interpretNote = ref('')
const showCypher = ref(false)
const booting = ref(true)

let healthTimer: number | undefined

// ------------------------------------------------------------ derived

const venuesById = computed(() => Object.fromEntries((state.value?.venues || []).map((v) => [v.id, v])))
const incident = computed(() => state.value?.incident || null)
const quickFix = computed(() => state.value?.quickFix || null)
const proposal = computed(() => recovery.value?.proposal || null)
const feasible = computed(() => proposal.value?.status === 'feasible')
const verified = computed(() => !!verification.value?.verification.passed)
const daytonaMode = computed(() => health.value?.daytona.mode || 'unconfigured')

const overlooked = computed<Violation[]>(() => (quickFix.value?.violations || []).filter((v) => v.code === 'ACCESS'))

const liveAssignment = computed(() => Object.fromEntries((state.value?.sessions || []).map((s) => [s.id, s.venue])))

const board = computed(() => {
  const live = liveAssignment.value
  if (view.value === 'quickfix' && quickFix.value) {
    const a = { ...live }
    const ghosts: Record<string, string> = {}
    for (const m of quickFix.value.moves) {
      a[m.sessionId] = m.to
      ghosts[m.sessionId] = m.from
    }
    return { assignment: a, ghosts, violations: quickFix.value.violations }
  }
  if (view.value === 'proposal' && proposal.value?.assignment && !verified.value) {
    const ghosts: Record<string, string> = {}
    for (const m of proposal.value.moves || []) ghosts[m.sessionId] = m.from
    return { assignment: proposal.value.assignment, ghosts, violations: proposal.value.violationsAfter || [] }
  }
  const ghosts: Record<string, string> = {}
  if (verified.value) for (const m of proposal.value?.moves || []) ghosts[m.sessionId] = m.from
  return { assignment: live, ghosts, violations: state.value?.violations || [] }
})

const steps = computed(() => {
  const s = [
    { key: 'detect', label: 'Detect', hint: 'Venue marked unavailable', done: !!incident.value || verified.value },
    { key: 'trace', label: 'Trace', hint: 'Neo4j finds who is affected', done: !!trace.value },
    { key: 'check', label: 'Check', hint: 'Rules test the quick fix', done: !!quickFix.value || verified.value },
    { key: 'recover', label: 'Recover', hint: 'Solver runs in Daytona', done: feasible.value, fail: proposal.value?.status === 'infeasible' },
    { key: 'approve', label: 'Approve', hint: 'Organiser accepts the plan', done: !!verification.value },
    { key: 'verify', label: 'Verify', hint: 'Re-check & record evidence', done: verified.value, fail: !!verification.value && !verified.value },
  ]
  const current = s.findIndex((x) => !x.done && !x.fail)
  return s.map((x, i) => ({ ...x, current: i === current && !!incident.value }))
})

const views = computed(() => {
  const v: { key: View; label: string; count?: number; tone?: string }[] = [
    { key: 'live', label: verified.value ? 'Live (after recovery)' : 'Live schedule', count: state.value?.violations.length, tone: state.value?.violations.length ? 'bad' : 'go' },
  ]
  if (quickFix.value?.moves.length && !verified.value) v.push({ key: 'quickfix', label: 'Quick fix', count: quickFix.value.unresolved, tone: quickFix.value.unresolved ? 'bad' : 'go' })
  if (proposal.value?.assignment && !verified.value) v.push({ key: 'proposal', label: 'Proposed recovery', count: proposal.value.violationsAfter?.length || 0, tone: 'go' })
  if (impact.value && incident.value && !verified.value) v.splice(1, 0, { key: 'impact', label: 'Impact graph' })
  if (provenance.value && verified.value) v.push({ key: 'provenance', label: 'Provenance graph' })
  return v
})

const twistCandidates = computed(() => {
  if (!proposal.value || !feasible.value || verified.value) return []
  const ids = new Set((proposal.value.moves || []).map((m) => m.to))
  return [...ids].map((id) => venuesById.value[id]).filter(Boolean)
})

// ------------------------------------------------------------ actions

async function run<T>(label: string, fn: () => Promise<T>): Promise<T | undefined> {
  busy.value = label
  error.value = ''
  try {
    return await fn()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = null
    refreshHealth()
  }
}

async function refreshHealth() {
  try {
    health.value = await api.health()
  } catch {
    health.value = null
  }
}

async function load() {
  await refreshHealth()
  if (health.value?.neo4j.ok && !health.value.neo4j.seeded) {
    const r = await api.reset()
    state.value = r.state
  } else {
    state.value = await api.state()
  }
  if (state.value?.incident) {
    trace.value = await api.trace(state.value.incident.venueId)
    memory.value = await api.memory(state.value.incident.venueId)
    impact.value = await api.impact()
    view.value = 'impact'
  }
}

function clearRun() {
  recovery.value = null
  verification.value = null
  provenance.value = null
  staleNote.value = ''
}

async function refreshImpact() {
  if (state.value?.incident && !verified.value) {
    try {
      impact.value = await api.impact()
    } catch {
      impact.value = null
    }
  }
}

async function closeVenue(venueId: string, note: string, source: string) {
  await run('close', async () => {
    const r = await api.close(venueId, note, source)
    clearRun()
    state.value = r.state
    trace.value = r.trace
    memory.value = r.memory
    impact.value = await api.impact()
    view.value = 'impact'
  })
}

async function submitReport() {
  await run('interpret', async () => {
    const r = await api.interpret(report.value)
    interpretNote.value = `${r.by === 'nosana' ? 'Nosana LLM' : 'Keyword match'}: ${r.summary}${r.warning ? ` (${r.warning})` : ''}`
    if (!r.venueId) throw new Error('No venue recognised in that report. Name the room, e.g. “Lecture Theatre 1”.')
    busy.value = null
    await closeVenue(r.venueId, report.value, `report/${r.by}`)
  })
}

async function toggleVenue(venueId: string, available: boolean) {
  if (!available && !incident.value) {
    const v = venuesById.value[venueId]
    return closeVenue(venueId, `${v?.name || venueId} marked unavailable`, 'dashboard')
  }
  await run('toggle', async () => {
    state.value = await api.setAvailability(venueId, available)
    await refreshImpact()
    if (recovery.value && !verified.value) {
      recovery.value = null
      staleNote.value = `${venuesById.value[venueId]?.name} is now ${available ? 'available' : 'unavailable'}. The previous proposal no longer reflects live state, so run recovery again.`
      view.value = 'live'
    }
  })
}

async function recover() {
  await run('recover', async () => {
    staleNote.value = ''
    recovery.value = await api.recover()
    view.value = recovery.value.proposal.status === 'feasible' ? 'proposal' : 'live'
  })
}

async function twist(venueId: string) {
  await run('toggle', async () => {
    state.value = await api.setAvailability(venueId, false)
    await refreshImpact()
    recovery.value = null
    view.value = 'live'
  })
  if (!error.value) await recover()
}

async function approve() {
  if (!recovery.value) return
  await run('approve', async () => {
    const r = await api.approve(recovery.value!.recovery.id)
    verification.value = r
    state.value = r.state
    provenance.value = await api.provenance(recovery.value!.recovery.id)
    view.value = 'provenance'
  })
}

async function reset(full = false) {
  if (full && !window.confirm('Wipe all recovery history from Neo4j? The next run will start with no memory.')) return
  await run('reset', async () => {
    const r = await api.reset(full)
    state.value = r.state
    trace.value = null
    impact.value = null
    memory.value = null
    clearRun()
    view.value = 'live'
    interpretNote.value = ''
  })
}

function fmtTime(iso?: string) {
  if (!iso) return ''
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function venueName(id?: string | null) {
  return (id && venuesById.value[id]?.name) || id || ''
}

onMounted(async () => {
  try {
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    booting.value = false
  }
  healthTimer = window.setInterval(refreshHealth, 5000)
})
onBeforeUnmount(() => window.clearInterval(healthTimer))
</script>

<template>
  <div class="app">
    <!-- ============================== header -->
    <header class="top">
      <div class="brand">
        <div class="logo" aria-hidden="true"><span /></div>
        <div>
          <div class="wordmark">WAY<b>FOUND</b></div>
          <div class="tagline">Autonomous recovery that accounts for everyone</div>
        </div>
      </div>
      <div class="status">
        <span class="chip" :class="health?.neo4j.ok ? 'info' : 'bad'" :title="health?.neo4j.error || `Database ${health?.neo4j.database}`">
          <span class="dot" />Neo4j {{ health?.neo4j.ok ? health.neo4j.version : 'offline' }}
        </span>
        <span
          class="chip"
          :class="daytonaMode === 'daytona' ? (health?.daytona.state === 'error' ? 'bad' : 'go') : daytonaMode === 'local' ? 'warn' : 'bad'"
          :title="health?.daytona.detail"
        >
          <span class="dot" :class="{ pulse: ['creating', 'starting', 'running'].includes(health?.daytona.state || '') }" />
          <template v-if="daytonaMode === 'daytona'">Daytona {{ health?.daytona.state === 'idle' ? 'connected' : health?.daytona.state }}</template>
          <template v-else-if="daytonaMode === 'local'">Local execution (not Daytona)</template>
          <template v-else>Daytona key missing</template>
        </span>
        <span class="chip" :class="health?.nosana.enabled ? 'go' : ''" :title="health?.nosana.enabled ? health.nosana.model || '' : 'Optional: explanations use a deterministic template'">
          <span class="dot" />Nosana {{ health?.nosana.enabled ? 'LLM' : 'off' }}
        </span>
        <button class="btn sm ghost" :disabled="!!busy" title="Reopen rooms and restore the timetable. Recovery history (memory) is kept." @click="reset()">
          <span v-if="busy === 'reset'" class="spinner" />Reset demo
        </button>
        <button class="btn sm ghost faint" :disabled="!!busy" title="Also delete all recovery history" @click="reset(true)">Wipe memory</button>
      </div>
    </header>

    <div v-if="!health && !booting" class="banner bad">
      The backend isn't reachable. Start it with <code>cd backend &amp;&amp; uv run uvicorn app.main:app --port 8010</code>.
    </div>
    <div v-else-if="health && !health.neo4j.ok" class="banner bad">Neo4j is not reachable: {{ health.neo4j.error }}</div>
    <div v-else-if="daytonaMode === 'unconfigured'" class="banner warn">
      <b>Daytona isn't configured.</b> Recovery and verification run only in a Daytona sandbox. Add <code>DAYTONA_API_KEY</code> to <code>.env</code> and restart the backend.
    </div>
    <div v-else-if="daytonaMode === 'local'" class="banner warn">
      Running the engine <b>locally</b> because <code>ALLOW_LOCAL_EXECUTION=true</code>. This is for offline development only, not the demo.
    </div>

    <transition name="fade">
      <div v-if="error" class="toast" role="alert">
        <span>{{ error }}</span>
        <button class="btn sm ghost" @click="error = ''">Dismiss</button>
      </div>
    </transition>

    <!-- ============================== steps -->
    <section class="rail">
      <div class="event" v-if="state">
        <div class="eyebrow">Event</div>
        <div class="ename">{{ state.event.name }}</div>
        <div class="muted">{{ state.event.date }} · {{ state.participantTotal }} participants · {{ state.sessions.length }} sessions · {{ state.venues.length }} venues</div>
      </div>
      <ol class="steps">
        <li v-for="(s, i) in steps" :key="s.key" :class="{ done: s.done, current: s.current, fail: s.fail }">
          <span class="num mono">{{ s.done ? '✓' : s.fail ? '!' : i + 1 }}</span>
          <span class="slabel">{{ s.label }}</span>
          <span class="shint">{{ s.hint }}</span>
        </li>
      </ol>
    </section>

    <main class="grid">
      <!-- ============================== board -->
      <section class="panel boardp">
        <div class="phead">
          <div>
            <div class="eyebrow">{{ view === 'impact' || view === 'provenance' ? 'Graph · live from Neo4j' : 'Operational state · read from Neo4j' }}</div>
            <h2>{{ view === 'impact' ? 'Who does this closure reach?' : view === 'provenance' ? 'Why is this plan trusted?' : 'Schedule' }}</h2>
          </div>
          <div class="tabs" role="tablist">
            <button
              v-for="v in views"
              :key="v.key"
              role="tab"
              :aria-selected="view === v.key"
              :class="{ active: view === v.key }"
              @click="view = v.key"
            >
              {{ v.label }}
              <span v-if="v.count !== undefined" class="count" :class="v.tone">{{ v.count === 0 ? '0 issues' : `${v.count} issue${v.count === 1 ? '' : 's'}` }}</span>
              <span v-else class="count info">graph</span>
            </button>
          </div>
        </div>
        <div v-if="booting" class="loading"><span class="spinner" /> Loading event state from Neo4j…</div>
        <div v-else-if="view === 'impact' && impact" class="graphwrap">
          <p class="gq">One graph traversal answers it: <b>Incident → closed room → session → attendee → requirement → rooms that provide it.</b>
            The red dashed edge is the capacity-only quick fix: enough seats, but no step-free route.</p>
          <div class="gscroll"><GraphView :graph="impact" /></div>
          <button class="linkish" @click="showGraphCypher = !showGraphCypher">{{ showGraphCypher ? 'Hide' : 'Show' }} the Cypher</button>
          <pre v-if="showGraphCypher" class="code">{{ impact.cypher }}</pre>
        </div>
        <div v-else-if="view === 'provenance' && provenance" class="graphwrap">
          <p class="gq">The audit trail written back to Neo4j: what was closed, what moved, which Daytona verification passed{{ provenance.edges.some((e) => e.label === 'INFORMED_BY') ? ', and which earlier recovery informed this one' : '' }}.</p>
          <div class="gscroll"><GraphView :graph="provenance" /></div>
        </div>
        <ScheduleBoard
          v-else-if="state"
          :venues="state.venues"
          :sessions="state.sessions"
          :assignment="board.assignment"
          :ghosts="board.ghosts"
          :violations="board.violations"
          :busy="!!busy"
          :locked-venue="incident?.venueId"
          :moved-label="view === 'quickfix' ? 'quick fix' : 'moved'"
          @toggle="toggleVenue"
        />
        <div v-if="view !== 'impact' && view !== 'provenance'" class="legend">
          <span><i class="lg ok" />Meets every hard constraint</span>
          <span><i class="lg bad" />Breaks a hard constraint</span>
          <span><i class="lg mv" />Moved by the plan</span>
          <span class="muted">Toggles mark rooms (un)available. That's the live twist.</span>
        </div>
      </section>

      <!-- ============================== workflow -->
      <aside class="flow">
        <!-- DETECT -->
        <section class="panel card" :class="{ active: !incident && !verified }">
          <div class="chead"><span class="n mono">01</span><h3>Detect</h3><span v-if="incident" class="chip bad"><span class="dot" />{{ incident.id }}</span></div>
          <template v-if="!incident">
            <p class="muted">Report the disruption in plain words, or close a room directly.</p>
            <textarea v-model="report" rows="2" :disabled="!!busy" aria-label="Incident report" />
            <div class="row">
              <button class="btn danger" :disabled="!!busy || !report.trim() || !health?.neo4j.ok" @click="submitReport">
                <span v-if="busy === 'interpret' || busy === 'close'" class="spinner" />Report incident
              </button>
              <button class="btn" :disabled="!!busy || !state?.venues.find((v) => v.id === 'LT1')?.available" @click="closeVenue('LT1', 'Lecture Theatre 1 closed by facilities', 'dashboard')">
                Close Lecture Theatre 1
              </button>
            </div>
            <p v-if="interpretNote" class="note mono">{{ interpretNote }}</p>
          </template>
          <template v-else>
            <p><b>{{ venueName(incident.venueId) }}</b> is unavailable.</p>
            <p class="muted quote">“{{ incident.note }}”</p>
            <p class="faint small mono">{{ incident.source }} · {{ fmtTime(incident.createdAt) }}</p>
          </template>
        </section>

        <!-- TRACE -->
        <section v-if="trace" class="panel card">
          <div class="chead"><span class="n mono">02</span><h3>Trace</h3><span class="chip info">Neo4j</span></div>
          <div class="stats">
            <div><b>{{ trace.sessions }}</b><span>session{{ trace.sessions === 1 ? '' : 's' }}</span></div>
            <div><b>{{ trace.attendees }}</b><span>attendees</span></div>
            <div><b>{{ trace.requirementHolders }}</b><span>hard requirement{{ trace.requirementHolders === 1 ? '' : 's' }}</span></div>
          </div>
          <div v-for="r in trace.rows" :key="r.session" class="trow">
            <div><span class="mono faint">{{ r.session }} · {{ r.start }}</span> {{ r.title }}</div>
            <div class="small muted">Needs {{ r.equipment.join(', ') || 'no equipment' }}</div>
            <div v-for="n in r.needs" :key="n.id" class="person">
              <span class="avatar">{{ n.name.split(' ').map((x) => x[0]).join('') }}</span>
              <span><b>{{ n.name }}</b> <span class="mono faint">{{ n.id }}</span></span>
              <span class="chip info">{{ n.requirement }}</span>
            </div>
          </div>
          <div v-if="memory" class="memory" :class="{ has: memory.recoveryId }">
            <div class="eyebrow">Graph memory</div>
            <p v-if="memory.recoveryId">
              This room has failed <b>{{ memory.priorIncidents }}</b> time{{ memory.priorIncidents === 1 ? '' : 's' }} before.
              Last verified fix <span class="mono">{{ memory.recoveryId }}</span>:
              <span v-for="m in memory.moves" :key="m.session">{{ m.session }} → {{ venueName(m.to) }} </span>
            </p>
            <p v-else-if="memory.priorIncidents">This room has failed {{ memory.priorIncidents }} time{{ memory.priorIncidents === 1 ? '' : 's' }} before, but no fix was verified.</p>
            <p v-else class="muted">No earlier incidents for this room. Whatever is verified now becomes the precedent next time.</p>
          </div>
          <button class="linkish" @click="showCypher = !showCypher">{{ showCypher ? 'Hide' : 'Show' }} the Cypher query</button>
          <pre v-if="showCypher" class="code">{{ trace.cypher }}</pre>
        </section>

        <!-- CHECK -->
        <section v-if="incident && quickFix" class="panel card" :class="{ alert: overlooked.length }">
          <div class="chead"><span class="n mono">03</span><h3>Check</h3><span class="chip" :class="quickFix.unresolved ? 'bad' : 'go'">{{ quickFix.unresolved }} violated</span></div>
          <p class="muted small">Quick fix: {{ quickFix.rule.toLowerCase() }}.</p>
          <div v-for="m in quickFix.moves" :key="m.sessionId" class="move">
            <span class="mono">{{ m.sessionId }}</span>
            <span>{{ venueName(m.from) }}</span><span class="arrow">→</span><b>{{ m.toName }}</b>
            <span class="chip go">{{ m.attendees }}/{{ m.capacity }} seats ✓</span>
          </div>
          <div v-if="overlooked.length" class="overlooked">
            <div class="eyebrow bad-t">Overlooked</div>
            <div v-for="v in overlooked" :key="v.participantId" class="ov">
              <div class="big">Capacity works, but not for everyone.</div>
              <p>{{ v.detail }}.</p>
              <p v-if="venuesById[v.venueId || '']?.accessNote" class="small muted">Venue record: {{ venuesById[v.venueId || ''].accessNote }}.</p>
            </div>
          </div>
          <ul v-for="v in quickFix.violations.filter((x) => x.code !== 'ACCESS')" :key="v.detail" class="vlist">
            <li><span class="mono">{{ v.code }}</span> {{ v.detail }}</li>
          </ul>
        </section>

        <!-- RECOVER -->
        <section v-if="incident || recovery" class="panel card" :class="{ active: incident && !recovery && !busy }">
          <div class="chead"><span class="n mono">04</span><h3>Recover</h3><span class="chip go" v-if="recovery?.execution.engine === 'daytona'">Daytona sandbox</span><span class="chip warn" v-else-if="recovery">local</span></div>
          <p v-if="staleNote" class="note warn-t">{{ staleNote }}</p>
          <template v-if="!recovery">
            <p class="muted">Search every feasible reassignment against live graph state. Feasibility is decided by deterministic code, never by an LLM.</p>
            <button class="btn primary lg wide" :disabled="!!busy || daytonaMode === 'unconfigured' || verified" @click="recover">
              <span v-if="busy === 'recover'" class="spinner" />
              {{ busy === 'recover' ? (health?.daytona.detail || 'Running in Daytona…') : 'Run recovery in Daytona' }}
            </button>
          </template>

          <template v-else>
            <div class="exec mono">
              <span>engine <b>{{ recovery.execution.engine }}</b></span>
              <span v-if="recovery.execution.sandboxId">sandbox <b>{{ recovery.execution.sandboxId.slice(0, 12) }}</b></span>
              <span>exit <b>{{ recovery.execution.exitCode }}</b></span>
              <span>{{ recovery.proposal.nodesExplored }} nodes · {{ recovery.proposal.elapsedMs }} ms solve · {{ recovery.execution.elapsedMs }} ms round-trip</span>
            </div>

            <div v-if="recovery.proposal.precedent" class="precedent" :class="recovery.proposal.precedent.valid ? 'ok' : 'stale'">
              <div class="eyebrow">Precedent {{ recovery.memory?.recoveryId }}</div>
              <p v-if="recovery.proposal.precedent.valid && recovery.proposal.precedent.followed">
                <b>Reused.</b> The plan verified last time was re-checked against today's state in Daytona and still satisfies every hard constraint.
              </p>
              <p v-else-if="!recovery.proposal.precedent.valid">
                <b>Not reused.</b> Last time's plan no longer holds: {{ recovery.proposal.precedent.violations.join('; ') }}. Computed a new plan instead.
              </p>
              <p v-else>Precedent still valid, but a plan with fewer moves exists.</p>
            </div>

            <template v-if="feasible">
              <div class="eyebrow">Plan · {{ recovery.proposal.sessionsMoved }} move{{ recovery.proposal.sessionsMoved === 1 ? '' : 's' }}</div>
              <div v-for="m in recovery.proposal.moves" :key="m.sessionId" class="move">
                <span class="mono">{{ m.sessionId }}</span>
                <span>{{ venueName(m.from) }}</span><span class="arrow">→</span><b>{{ m.toName }}</b>
                <span class="chip" :class="m.reason === 'disrupted' ? 'bad' : 'info'">{{ m.reason }}</span>
              </div>
              <div class="explain">
                <div class="eyebrow">Explanation · {{ recovery.explanation.by === 'nosana' ? 'Nosana LLM' : 'deterministic template' }}</div>
                <p>{{ recovery.explanation.text }}</p>
                <p v-if="recovery.explanation.warning" class="small warn-t">{{ recovery.explanation.warning }}</p>
              </div>
              <details class="why">
                <summary>Why not the other rooms?</summary>
                <div v-for="(list, sid) in recovery.proposal.rejectedVenues" :key="sid">
                  <div v-for="r in list" :key="r.venueId" class="rej">
                    <b>{{ r.venueName }}</b>
                    <span v-for="x in r.reasons" :key="x" class="small muted">{{ x }}</span>
                  </div>
                </div>
              </details>
            </template>

            <template v-else>
              <div class="infeasible">
                <div class="big">No feasible recovery exists.</div>
                <p>{{ recovery.proposal.reason }}</p>
                <div v-for="b in recovery.proposal.blockedSessions" :key="b.sessionId" class="blocked">
                  <div class="small"><span class="mono">{{ b.sessionId }}</span> {{ b.sessionTitle }} · {{ b.attendees }} attendees</div>
                  <div v-for="r in b.rejectedVenues" :key="r.venueId" class="rej small">
                    <b>{{ r.venueName }}</b> <span class="muted">{{ r.reasons.join('; ') }}</span>
                  </div>
                </div>
                <p class="small muted">The system reports this honestly rather than guessing. Re-open a room to continue.</p>
              </div>
              <button class="btn wide" :disabled="!!busy" @click="recover"><span v-if="busy === 'recover'" class="spinner" />Run recovery again</button>
            </template>

            <div v-if="twistCandidates.length" class="twist">
              <div class="eyebrow">Live twist</div>
              <p class="small muted">Take a room the plan relies on away, then rerun. The answer must change or honestly fail.</p>
              <div class="row">
                <button v-for="v in twistCandidates" :key="v.id" class="btn sm" :disabled="!!busy" @click="twist(v.id)">Disable {{ v.name }} &amp; rerun</button>
              </div>
            </div>
          </template>
        </section>

        <!-- APPROVE -->
        <section v-if="feasible && !verification" class="panel card active">
          <div class="chead"><span class="n mono">05</span><h3>Approve</h3></div>
          <p class="muted">Nothing changes until you approve. On approval the backend applies the moves to the simulated schedule in Neo4j in one transaction.</p>
          <button class="btn primary lg wide" :disabled="!!busy" @click="approve">
            <span v-if="busy === 'approve'" class="spinner" />
            {{ busy === 'approve' ? 'Applying and verifying in Daytona…' : `Approve & apply ${recovery?.proposal.sessionsMoved} move${recovery?.proposal.sessionsMoved === 1 ? '' : 's'}` }}
          </button>
        </section>

        <!-- VERIFY -->
        <section v-if="verification" class="panel card" :class="verified ? 'verified' : 'alert'">
          <div class="chead"><span class="n mono">06</span><h3>Verify</h3><span class="chip" :class="verified ? 'go' : 'bad'">{{ verification.verification.status.replace('_', ' ') }}</span></div>
          <div class="vbig">
            <span class="num">{{ verification.verification.unresolved }}</span>
            <span>unresolved hard constraints across {{ verification.verification.sessions }} sessions ({{ verification.verification.constraintChecks }} checks), re-read from Neo4j after the change.</span>
          </div>
          <ul v-if="verification.verification.violations.length" class="vlist">
            <li v-for="v in verification.verification.violations" :key="v.detail"><span class="mono">{{ v.code }}</span> {{ v.detail }}</li>
          </ul>
          <div class="evidence mono">
            <div><span>recovery</span><b>{{ recovery?.recovery.id }}</b></div>
            <div><span>verification</span><b>{{ verification.verification.id }}</b></div>
            <div><span>engine</span><b>{{ verification.execution.engine }}{{ verification.execution.sandboxId ? ' · ' + verification.execution.sandboxId.slice(0, 12) : '' }}</b></div>
            <div><span>recorded</span><b>{{ fmtTime(verification.verification.createdAt) }}</b></div>
          </div>
          <pre class="code">MATCH (ra:RecoveryAction {id: '{{ recovery?.recovery.id }}'})-[r]->(n)
RETURN ra, r, n</pre>
          <p class="small muted">Evidence is stored in Neo4j. Run the query above in Aura to inspect it. Next time this room closes, this verified plan is the precedent.</p>
          <button v-if="provenance" class="btn sm" @click="view = 'provenance'">Show provenance graph</button>
        </section>
      </aside>
    </main>

    <!-- ============================== people + history -->
    <section class="lower">
      <div class="panel card">
        <div class="chead"><h3>People with hard requirements</h3></div>
        <p class="small muted">Out of {{ state?.participantTotal }} synthetic participants. These are the people a capacity-only fix silently ignores.</p>
        <div v-for="p in state?.requirementHolders" :key="p.id" class="person">
          <span class="avatar">{{ p.name.split(' ').map((x) => x[0]).join('') }}</span>
          <span><b>{{ p.name }}</b> <span class="mono faint">{{ p.id }}</span></span>
          <span v-for="r in p.requirements" :key="r" class="chip info">{{ REQUIREMENT_LABELS[r] || r }}</span>
        </div>
      </div>
      <div class="panel card">
        <div class="chead"><h3>Recovery history</h3><span class="chip">stored in Neo4j</span></div>
        <p v-if="!state?.history.length" class="small muted">No recoveries yet.</p>
        <table v-else class="hist">
          <thead><tr><th>Time</th><th>Incident</th><th>Plan</th><th>Engine</th><th>Result</th></tr></thead>
          <tbody>
            <tr v-for="h in state.history" :key="h.ra.id">
              <td class="mono">{{ fmtTime(h.ra.createdAt) }}</td>
              <td>{{ h.venue || '—' }}</td>
              <td>{{ h.ra.moves.map((m) => `${m.sessionId}→${m.toName}`).join(', ') || h.ra.summary }}</td>
              <td class="mono">{{ h.ra.engine }}</td>
              <td>
                <span class="chip" :class="{ verified: 'go', proposed: 'info', applied: 'info', superseded: '' }[h.ra.status] ?? 'bad'">{{ h.ra.status.replace('_', ' ') }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <footer>
      <p>“Most recovery systems ask whether the operation can continue. <b>Wayfound asks whether everyone can continue with it.</b>”</p>
      <p class="faint small">Synthetic data only · Daytona HackSprint Singapore 2026</p>
    </footer>
  </div>
</template>

<style scoped>
.app { max-width: 1440px; margin: 0 auto; padding: 20px 24px 40px; }

.top { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.brand { display: flex; align-items: center; gap: 12px; }
.logo { width: 38px; height: 38px; border-radius: 11px; background: #121a15; border: 1px solid var(--line-2); display: grid; place-items: center; position: relative; }
.logo::before { content: ''; width: 18px; height: 18px; border-radius: 50%; border: 3px solid var(--go); }
.logo span { position: absolute; width: 7px; height: 7px; border-radius: 50%; background: var(--bad); }
.wordmark { font-weight: 500; letter-spacing: .18em; font-size: 15px; }
.wordmark b { color: var(--go); font-weight: 700; }
.tagline { color: var(--muted); font-size: 12.5px; }
.status { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }

.banner { margin-top: 14px; padding: 10px 14px; border-radius: 10px; font-size: 13px; }
.banner.bad { background: var(--bad-soft); border: 1px solid rgba(255,122,89,.35); }
.banner.warn { background: var(--warn-soft); border: 1px solid rgba(255,200,87,.35); }

.toast {
  position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%); z-index: 20;
  display: flex; gap: 12px; align-items: center; max-width: min(720px, calc(100vw - 32px));
  background: #2a1712; border: 1px solid var(--bad); color: #ffd9cf; padding: 10px 10px 10px 16px; border-radius: 12px;
  box-shadow: 0 10px 40px rgba(0,0,0,.5); white-space: pre-wrap;
}

.rail { margin-top: 18px; display: grid; grid-template-columns: minmax(240px, 320px) 1fr; gap: 20px; align-items: center; }
.ename { font-weight: 700; font-size: 17px; }
.steps { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(6, 1fr); gap: 8px; }
.steps li { border: 1px solid var(--line); border-radius: 12px; padding: 10px 12px; display: grid; grid-template-columns: auto 1fr; column-gap: 8px; background: var(--bg-2); transition: all .25s; }
.steps .num { grid-row: span 2; width: 24px; height: 24px; border-radius: 50%; display: grid; place-items: center; font-size: 11.5px; border: 1px solid var(--line-2); color: var(--muted); align-self: center; }
.steps .slabel { font-weight: 600; font-size: 13px; }
.steps .shint { font-size: 11px; color: var(--faint); line-height: 1.3; }
.steps li.done { border-color: rgba(198,243,107,.3); }
.steps li.done .num { background: var(--go); color: var(--go-ink); border-color: var(--go); font-weight: 700; }
.steps li.current { border-color: var(--go); box-shadow: 0 0 0 3px var(--go-soft); }
.steps li.current .num { border-color: var(--go); color: var(--go); }
.steps li.fail { border-color: rgba(255,122,89,.5); }
.steps li.fail .num { background: var(--bad); color: #2a0d05; border-color: var(--bad); font-weight: 700; }

.grid { margin-top: 16px; display: grid; grid-template-columns: minmax(0, 1fr) 400px; gap: 16px; align-items: start; }
.boardp { padding: 16px 18px; position: sticky; top: 16px; min-width: 0; }
.grid > *, .lower > * { min-width: 0; }
.phead { display: flex; justify-content: space-between; align-items: end; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }
h2 { margin: 2px 0 0; font-size: 18px; }
h3 { margin: 0; font-size: 15px; }
.tabs { display: flex; gap: 4px; background: var(--bg); border: 1px solid var(--line); border-radius: 11px; padding: 3px; flex-wrap: wrap; }
.tabs button { border: 0; background: transparent; padding: 6px 10px; border-radius: 8px; cursor: pointer; font-size: 12.5px; font-weight: 600; color: var(--muted); display: inline-flex; gap: 6px; align-items: center; }
.tabs button.active { background: var(--panel-2); color: var(--text); }
.count { font-size: 10.5px; padding: 0 6px; border-radius: 999px; font-weight: 600; }
.count.bad { background: var(--bad-soft); color: var(--bad); }
.count.go { background: var(--go-soft); color: var(--go); }
.loading { display: flex; gap: 10px; align-items: center; color: var(--muted); padding: 40px 0; justify-content: center; }
.legend { display: flex; gap: 16px; flex-wrap: wrap; margin-top: 12px; font-size: 12px; color: var(--muted); align-items: center; }
.legend span { display: inline-flex; gap: 6px; align-items: center; }
.lg { width: 12px; height: 12px; border-radius: 3px; display: inline-block; border: 1px solid #36493d; background: #213028; }
.lg.bad { border-color: var(--bad); background: #3a1e17; }
.lg.mv { border-color: var(--go); box-shadow: 0 0 0 2px var(--go-soft); }

.flow { display: flex; flex-direction: column; gap: 12px; }
.card { padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; }
.card p { margin: 0; }
.card.active { border-color: rgba(198,243,107,.45); box-shadow: 0 0 0 3px var(--go-soft); }
.card.alert { border-color: rgba(255,122,89,.5); }
.card.verified { border-color: rgba(198,243,107,.55); background: linear-gradient(180deg, #18240f, var(--bg-2)); }
.chead { display: flex; align-items: center; gap: 10px; }
.chead .chip { margin-left: auto; }
.chead .chip + .chip { margin-left: 0; }
.n { color: var(--faint); font-size: 11px; }
.row { display: flex; gap: 8px; flex-wrap: wrap; }
.wide { width: 100%; }
.small { font-size: 12px; }
.quote { font-style: italic; }
.note { font-size: 11.5px; color: var(--muted); }
.warn-t { color: var(--warn); }
.bad-t { color: var(--bad); }
textarea {
  width: 100%; resize: vertical; background: var(--bg); color: var(--text); border: 1px solid var(--line-2);
  border-radius: 10px; padding: 10px 12px; font: inherit; font-size: 13px; line-height: 1.45;
}
textarea:focus { outline: none; border-color: var(--go); }

.stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.stats div { background: var(--bg); border: 1px solid var(--line); border-radius: 10px; padding: 8px 10px; display: flex; flex-direction: column; }
.stats b { font-size: 20px; font-variant-numeric: tabular-nums; }
.stats span { font-size: 11px; color: var(--muted); }
.trow { display: flex; flex-direction: column; gap: 6px; padding-top: 4px; }
.person { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: 10px; background: var(--info-soft); border: 1px solid rgba(124,196,255,.25); flex-wrap: wrap; }
.person .chip { margin-left: auto; }
.avatar { width: 28px; height: 28px; border-radius: 50%; background: #1d3347; color: var(--info); display: grid; place-items: center; font-size: 11px; font-weight: 700; flex: none; }
.linkish { background: none; border: 0; color: var(--info); cursor: pointer; padding: 0; font-size: 12px; text-align: left; }

.move { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 13px; padding: 8px 10px; border: 1px solid var(--line); border-radius: 10px; background: var(--bg); }
.move .chip { margin-left: auto; }
.arrow { color: var(--faint); }
.overlooked { border-radius: 12px; padding: 12px; background: var(--bad-soft); border: 1px solid rgba(255,122,89,.4); display: flex; flex-direction: column; gap: 6px; }
.big { font-weight: 700; font-size: 15.5px; }
.vlist { margin: 0; padding-left: 18px; color: var(--muted); font-size: 12.5px; }

.exec { display: flex; flex-wrap: wrap; gap: 6px 12px; font-size: 11px; color: var(--muted); padding: 8px 10px; background: #070a08; border: 1px solid var(--line); border-radius: 10px; }
.exec b { color: var(--go); font-weight: 500; }
.explain { background: var(--panel-2); border-radius: 10px; padding: 10px 12px; display: flex; flex-direction: column; gap: 4px; }
.why summary { cursor: pointer; color: var(--info); font-size: 12.5px; }
.why[open] summary { margin-bottom: 6px; }
.rej { display: flex; flex-direction: column; gap: 1px; padding: 5px 0; border-top: 1px solid var(--line); }
.infeasible { border-radius: 12px; padding: 12px; background: var(--bad-soft); border: 1px solid rgba(255,122,89,.4); display: flex; flex-direction: column; gap: 8px; }
.blocked { display: flex; flex-direction: column; gap: 2px; }
.twist { border-top: 1px dashed var(--line-2); padding-top: 10px; display: flex; flex-direction: column; gap: 6px; }

.vbig { display: flex; gap: 14px; align-items: center; }
.vbig .num { font-size: 52px; font-weight: 700; line-height: 1; color: var(--go); font-variant-numeric: tabular-nums; }
.card.alert .vbig .num { color: var(--bad); }
.vbig span:last-child { color: var(--muted); font-size: 12.5px; }
.evidence { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; font-size: 11px; }
.evidence div { background: var(--bg); border: 1px solid var(--line); border-radius: 8px; padding: 6px 8px; display: flex; flex-direction: column; min-width: 0; }
.evidence span { color: var(--faint); }
.evidence b { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.graphwrap { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.graphwrap :deep(.graph) { min-width: 880px; }
.gscroll { overflow-x: auto; }
.gq { margin: 0; color: var(--muted); font-size: 13px; }
.gq b { color: var(--text); font-weight: 600; }
.count.info { background: var(--info-soft); color: var(--info); }
.memory { border-radius: 10px; padding: 10px 12px; border: 1px dashed var(--line-2); display: flex; flex-direction: column; gap: 4px; font-size: 12.5px; }
.memory.has { border: 1px solid rgba(184,156,255,.45); background: rgba(184,156,255,.08); }
.memory.has .eyebrow { color: var(--violet); }
.precedent { border-radius: 10px; padding: 10px 12px; font-size: 12.5px; display: flex; flex-direction: column; gap: 4px; }
.precedent.ok { background: rgba(184,156,255,.08); border: 1px solid rgba(184,156,255,.45); }
.precedent.ok .eyebrow { color: var(--violet); }
.precedent.stale { background: var(--warn-soft); border: 1px solid rgba(255,200,87,.4); }
.precedent.stale .eyebrow { color: var(--warn); }
.lower { margin-top: 16px; display: grid; grid-template-columns: 1fr 2fr; gap: 16px; }
.hist { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.hist th { text-align: left; font-weight: 600; color: var(--faint); font-size: 11px; text-transform: uppercase; letter-spacing: .08em; padding: 6px 8px; border-bottom: 1px solid var(--line); }
.hist td { padding: 8px; border-bottom: 1px solid var(--line); vertical-align: top; }

footer { margin-top: 28px; text-align: center; }
footer p { margin: 4px 0; }
footer p:first-child { font-size: 15px; color: var(--muted); }
footer b { color: var(--text); font-weight: 600; }

@media (max-width: 1180px) {
  .grid { grid-template-columns: 1fr; }
  .boardp { position: static; }
  .rail { grid-template-columns: 1fr; }
  .steps { grid-template-columns: repeat(3, 1fr); }
  .lower { grid-template-columns: 1fr; }
}
@media (max-width: 640px) {
  .app { padding: 14px 16px 32px; }
  .steps { grid-template-columns: repeat(2, 1fr); }
  .hist { display: block; overflow-x: auto; }
}
</style>
