<script setup lang="ts">
import { computed } from 'vue'
import type { Session, Venue, Violation } from '../api'
import { RESOURCE_LABELS } from '../api'

const props = defineProps<{
  venues: Venue[]
  sessions: Session[]
  assignment: Record<string, string>
  ghosts: Record<string, string>
  violations: Violation[]
  busy: boolean
  lockedVenue?: string | null
  movedLabel?: string
}>()

const emit = defineEmits<{ toggle: [venueId: string, available: boolean] }>()

const START = 8 * 60 + 30
const END = 15 * 60 + 30
const hours = ['09:00', '10:00', '11:00', '12:00', '13:00', '14:00', '15:00']

function mins(t: string) {
  const [h, m] = t.split(':').map(Number)
  return h * 60 + m
}
function pos(start: string, end: string) {
  const span = END - START
  return {
    left: `${((mins(start) - START) / span) * 100}%`,
    width: `${((mins(end) - mins(start)) / span) * 100}%`,
  }
}

const bySession = computed(() => {
  const out: Record<string, Violation[]> = {}
  for (const v of props.violations) (out[v.sessionId] ||= []).push(v)
  return out
})

const rows = computed(() =>
  props.venues.map((v) => ({
    venue: v,
    blocks: props.sessions
      .filter((s) => props.assignment[s.id] === v.id)
      .map((s) => ({
        s,
        moved: props.ghosts[s.id] !== undefined,
        issues: bySession.value[s.id] || [],
        fill: Math.round((s.attendeeCount / v.capacity) * 100),
      })),
    ghosts: props.sessions.filter((s) => props.ghosts[s.id] === v.id),
  })),
)
</script>

<template>
  <div class="board">
    <div class="scale">
      <div class="venue-col faint">Venue</div>
      <div class="track">
        <span v-for="h in hours" :key="h" class="tick mono" :style="{ left: pos(h, h).left }">{{ h }}</span>
      </div>
    </div>

    <div v-for="r in rows" :key="r.venue.id" class="row" :class="{ closed: !r.venue.available }">
      <div class="venue-col">
        <div class="vname">
          <span>{{ r.venue.name }}</span>
          <button
            class="switch"
            :class="{ on: r.venue.available }"
            :disabled="busy || lockedVenue === r.venue.id"
            :title="lockedVenue === r.venue.id ? 'Closed by the active incident' : r.venue.available ? 'Mark unavailable' : 'Mark available'"
            :aria-label="`${r.venue.name} ${r.venue.available ? 'available' : 'unavailable'}`"
            @click="emit('toggle', r.venue.id, !r.venue.available)"
          >
            <span />
          </button>
        </div>
        <div class="vmeta">
          <span class="mono">{{ r.venue.capacity }} seats</span>
          <span v-if="r.venue.stepFree" class="acc ok" title="Step-free route">
            <svg viewBox="0 0 16 16" width="12" height="12"><path fill="currentColor" d="M6.5 1.5a1.5 1.5 0 1 1 0 3 1.5 1.5 0 0 1 0-3zM5 5.5h3v3h3.2l1.6 4.1-1.4.5-1.2-3.1H6.8a1.8 1.8 0 0 1-1.8-1.8V5.5zM4 8.2v1.3A3.5 3.5 0 0 0 9.2 13l.7 1.1A4.8 4.8 0 0 1 2.7 9.5 4.7 4.7 0 0 1 4 8.2z"/></svg>
            step-free
          </span>
          <span v-else class="acc no" :title="r.venue.accessNote || 'No step-free route'">
            <svg viewBox="0 0 16 16" width="12" height="12"><path fill="none" stroke="currentColor" stroke-width="1.6" d="M2 13h3v-3h3V7h3V4h3"/></svg>
            stairs only
          </span>
        </div>
        <div class="res">
          <span v-for="res in r.venue.resources" :key="res">{{ RESOURCE_LABELS[res] || res }}</span>
        </div>
      </div>

      <div class="track lane">
        <div v-for="h in hours" :key="h" class="grid" :style="{ left: pos(h, h).left }" />
        <div v-if="!r.venue.available" class="closed-label mono">UNAVAILABLE</div>

        <div v-for="g in r.ghosts" :key="'g' + g.id" class="ghost" :style="pos(g.start, g.end)">
          <span class="mono">{{ g.id }}</span> was here
        </div>

        <div
          v-for="b in r.blocks"
          :key="b.s.id"
          class="block"
          :class="{ bad: b.issues.length, moved: b.moved }"
          :style="pos(b.s.start, b.s.end)"
          :title="b.issues.map((i) => i.detail).join('\n') || b.s.title"
        >
          <div class="btop">
            <span class="sid mono">{{ b.s.id }}</span>
            <span v-if="b.moved" class="tag" :class="{ bad: b.issues.length }">{{ movedLabel || 'moved' }}</span>
            <span v-if="b.s.needs.length" class="need" :title="b.s.needs.map((n) => `${n.name}: ${n.requirements.join(', ')}`).join('\n')">
              <svg viewBox="0 0 16 16" width="11" height="11"><path fill="currentColor" d="M6.5 1.5a1.5 1.5 0 1 1 0 3 1.5 1.5 0 0 1 0-3zM5 5.5h3v3h3.2l1.6 4.1-1.4.5-1.2-3.1H6.8a1.8 1.8 0 0 1-1.8-1.8V5.5zM4 8.2v1.3A3.5 3.5 0 0 0 9.2 13l.7 1.1A4.8 4.8 0 0 1 2.7 9.5 4.7 4.7 0 0 1 4 8.2z"/></svg>
              {{ b.s.needs.length }}
            </span>
          </div>
          <div class="btitle">{{ b.s.title }}</div>
          <div class="bfoot mono">
            <span>{{ b.s.attendeeCount }}/{{ r.venue.capacity }}</span>
            <span class="bar"><i :style="{ width: Math.min(b.fill, 100) + '%' }" :class="{ over: b.fill > 100 }" /></span>
          </div>
          <div v-if="b.issues.length" class="issue">{{ b.issues.length }} hard constraint{{ b.issues.length > 1 ? 's' : '' }} broken</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.board { display: flex; flex-direction: column; gap: 6px; }
.scale, .row { display: grid; grid-template-columns: 200px 1fr; gap: 12px; align-items: stretch; }
.scale { height: 22px; }
.venue-col { min-width: 0; }
.scale .venue-col { font-size: 11px; text-transform: uppercase; letter-spacing: .1em; align-self: end; }
.track { position: relative; }
.tick { position: absolute; bottom: 2px; transform: translateX(-50%); color: var(--faint); font-size: 10.5px; }

.row {
  min-height: 92px; padding: 8px 0; border-top: 1px solid var(--line);
  transition: opacity .2s;
}
.row .venue-col { display: flex; flex-direction: column; gap: 5px; padding-top: 2px; }
.vname { display: flex; align-items: center; justify-content: space-between; gap: 8px; font-weight: 600; font-size: 13.5px; }
.vmeta { display: flex; gap: 8px; align-items: center; font-size: 11.5px; color: var(--muted); }
.acc { display: inline-flex; gap: 4px; align-items: center; }
.acc.ok { color: var(--go); }
.acc.no { color: var(--warn); }
.res { display: flex; flex-wrap: wrap; gap: 4px; }
.res span { font-size: 10.5px; color: var(--faint); border: 1px solid var(--line); border-radius: 5px; padding: 0 5px; }

.lane { background: rgba(255,255,255,.012); border-radius: 10px; border: 1px solid var(--line); overflow: hidden; }
.grid { position: absolute; top: 0; bottom: 0; width: 1px; background: var(--line); opacity: .6; }
.row.closed .lane {
  background: repeating-linear-gradient(-45deg, rgba(255,122,89,.07) 0 8px, transparent 8px 16px);
  border-color: rgba(255,122,89,.35);
}
.row.closed .vname span:first-child { color: var(--bad); text-decoration: line-through; text-decoration-thickness: 1px; }
.closed-label { position: absolute; right: 10px; top: 8px; font-size: 10.5px; color: var(--bad); letter-spacing: .12em; }

.block {
  position: absolute; top: 6px; bottom: 6px; padding: 6px 9px; border-radius: 9px;
  background: linear-gradient(180deg, #213028, #1a251f);
  border: 1px solid #36493d; overflow: hidden;
  display: flex; flex-direction: column; gap: 2px;
  transition: left .5s cubic-bezier(.2,.8,.2,1), border-color .2s, background .2s;
}
.block.moved { border-color: var(--go); box-shadow: 0 0 0 3px var(--go-soft); }
.block.bad { border-color: var(--bad); background: linear-gradient(180deg, #3a1e17, #2a1712); box-shadow: 0 0 0 3px var(--bad-soft); }
.btop { display: flex; align-items: center; gap: 6px; }
.sid { font-size: 10.5px; color: var(--muted); }
.tag.bad { background: var(--bad); color: #2a0d05; }
.tag { font-size: 10px; font-weight: 700; color: var(--go-ink); background: var(--go); border-radius: 4px; padding: 0 5px; text-transform: uppercase; letter-spacing: .05em; }
.need { margin-left: auto; display: inline-flex; gap: 3px; align-items: center; font-size: 10.5px; color: var(--info); }
.btitle { font-size: 12px; font-weight: 600; line-height: 1.25; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.bfoot { margin-top: auto; display: flex; align-items: center; gap: 6px; font-size: 10.5px; color: var(--muted); }
.bar { flex: 1; height: 4px; background: rgba(255,255,255,.08); border-radius: 2px; overflow: hidden; }
.bar i { display: block; height: 100%; background: var(--go); border-radius: 2px; }
.bar i.over { background: var(--bad); }
.issue { font-size: 10.5px; color: var(--bad); font-weight: 600; }
.ghost {
  position: absolute; top: 6px; bottom: 6px; border-radius: 9px; border: 1.5px dashed var(--line-2);
  display: flex; align-items: center; justify-content: center; gap: 4px; font-size: 11px; color: var(--faint);
}

.switch {
  width: 34px; height: 20px; border-radius: 999px; border: 1px solid var(--line-2); background: #2a1a16;
  position: relative; cursor: pointer; flex: none; padding: 0; transition: background .2s, border-color .2s;
}
.switch span { position: absolute; top: 2px; left: 2px; width: 14px; height: 14px; border-radius: 50%; background: var(--bad); transition: left .2s, background .2s; }
.switch.on { background: #1d2a13; border-color: rgba(198,243,107,.4); }
.switch.on span { left: 16px; background: var(--go); }
.switch:disabled { opacity: .45; cursor: not-allowed; }

@media (max-width: 760px) {
  .scale, .row { grid-template-columns: 1fr; }
  .scale .venue-col { display: none; }
  .row { min-height: 0; }
  .lane { height: 96px; }
}
</style>
