<script>
  import { ARMS, pct, rampColor } from './format.js';

  /** @type {{ cells: any[] }} all summary cells of the run (every arm) */
  let { cells } = $props();

  let chosen = $state('');
  let cellIds = $derived([...new Set(cells.map((c) => c.cell))].sort());
  let arms = $derived(ARMS.filter((a) => cells.some((c) => c.arm === a)));

  // Pool pass/fail counts per check and arm, over one cell or all of them.
  let rows = $derived.by(() => {
    const pooled = {};
    for (const c of cells) {
      if (chosen && c.cell !== chosen) continue;
      for (const [id, v] of Object.entries(c.checks)) {
        pooled[id] ??= {};
        const slot = (pooled[id][c.arm] ??= { pass: 0, fail: 0 });
        slot.pass += v.pass;
        slot.fail += v.fail;
      }
    }
    return Object.entries(pooled)
      .map(([id, byArm]) => {
        const rate = (a) => {
          const s = byArm[a];
          return s && s.pass + s.fail ? s.pass / (s.pass + s.fail) : null;
        };
        return { id, byArm, rate, reading: reading(rate('implicit'), rate('explicit')) };
      })
      .sort((a, b) => (a.rate('implicit') ?? 2) - (b.rate('implicit') ?? 2));
  });

  function reading(implicit, explicit) {
    if (implicit == null) return { label: 'no data', kind: 'none' };
    if (implicit >= 0.8) return { label: 'applied unprompted', kind: 'ok' };
    if (explicit == null) return { label: 'gap (explicit arm not run)', kind: 'gap' };
    if (explicit >= 0.8) return { label: 'disposition gap: knows it, skips it', kind: 'disposition' };
    return { label: 'knowledge gap: fails even when told', kind: 'knowledge' };
  }
</script>

<div class="filters">
  <label>
    Scope
    <select bind:value={chosen}>
      <option value="">all cells pooled</option>
      {#each cellIds as id (id)}<option value={id}>{id}</option>{/each}
    </select>
  </label>
</div>
<div class="scroll">
  <table>
    <thead>
      <tr>
        <th>Check</th>
        {#each arms as a (a)}<th class="rate">{a}</th>{/each}
        <th>Reading (implicit → explicit)</th>
      </tr>
    </thead>
    <tbody>
      {#each rows as row (row.id)}
        <tr>
          <td class="mono">{row.id}</td>
          {#each arms as a (a)}
            {@const r = row.rate(a)}
            {@const s = row.byArm[a]}
            {#if r == null}
              <td class="rate empty">n/a</td>
            {:else}
              {@const c = rampColor(r)}
              <td class="rate" style:background={c.fill} style:color={c.ink} title={`${s.pass} pass, ${s.fail} fail`}>
                {pct(r)} <small style:color={c.ink}>n={s.pass + s.fail}</small>
              </td>
            {/if}
          {/each}
          <td class={`reading ${row.reading.kind}`}>{row.reading.label}</td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>

<style>
  .filters { display: flex; gap: 1rem; margin: 0.5rem 0; }
  .filters label { display: flex; align-items: center; gap: 0.4rem; color: var(--text-secondary); font-size: 0.9rem; }
  select { font: inherit; padding: 0.2rem 0.4rem; background: var(--surface-1); color: var(--text-primary); border: 1px solid var(--rule); border-radius: 4px; }
  .scroll { overflow-x: auto; background: var(--surface-1); border: 1px solid var(--rule); border-radius: 6px; }
  table { border-collapse: separate; border-spacing: 2px; font-size: 0.85rem; }
  th, td { padding: 0.35rem 0.6rem; text-align: left; white-space: nowrap; }
  th { color: var(--text-secondary); font-weight: 600; }
  .rate { text-align: center; min-width: 6rem; border-radius: 4px; font-variant-numeric: tabular-nums; }
  .rate small { opacity: 0.8; margin-left: 0.2rem; }
  .empty { background: var(--neutral); color: var(--text-muted); }
  .mono { font-family: var(--mono); font-size: 0.8rem; }
  .reading { color: var(--text-secondary); }
  .reading.knowledge, .reading.disposition { color: var(--text-primary); font-weight: 600; }
</style>
