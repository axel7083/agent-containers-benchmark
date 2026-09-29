<script>
  import { resolve } from '$app/paths';
  import { pct, rampColor } from './format.js';

  /** @type {{ rows: string[], columns: { key: string, label: string, sub: string }[], value: (row: string, colKey: string) => { rate: number | null, pass: number, fail: number, na: number } | undefined, rowLabel?: (row: string) => string, rowHref?: boolean }} */
  let { rows, columns, value, rowLabel = (r) => r, rowHref = false } = $props();

  let hover = $state(null);
</script>

<div class="heatmap" role="table" aria-label="Pass rate per check and cell">
  <div class="grid" style:grid-template-columns={`minmax(11rem, max-content) repeat(${columns.length}, minmax(5.5rem, 9rem))`}>
    <div class="corner" role="columnheader">check</div>
    {#each columns as col (col.key)}
      <div class="colhead" role="columnheader" title={col.key}>
        <span>{col.label}</span><small>{col.sub}</small>
      </div>
    {/each}
    {#each rows as row (row)}
      <div class="rowhead" role="rowheader" title={row}>
        {#if rowHref}<a href={resolve('/checks/[id]', { id: row })}>{rowLabel(row)}</a>{:else}{rowLabel(row)}{/if}
      </div>
      {#each columns as col (col.key)}
        {@const v = value(row, col.key)}
        {#if v && v.rate != null}
          {@const c = rampColor(v.rate)}
          <button
            type="button"
            class="cell"
            style:background={c.fill}
            style:color={c.ink}
            onmouseenter={() => (hover = { row, col, v })}
            onmouseleave={() => (hover = null)}
            onfocus={() => (hover = { row, col, v })}
            onblur={() => (hover = null)}
            aria-label={`${row} on ${col.label} ${col.sub}: ${pct(v.rate)} (${v.pass} pass, ${v.fail} fail)`}
          >
            {pct(v.rate)}
          </button>
        {:else}
          <div class="cell empty" aria-label={`${row} on ${col.label}: not applicable`}>n/a</div>
        {/if}
      {/each}
    {/each}
  </div>
  <p class="tip" aria-live="polite">
    {#if hover}
      <strong>{hover.row}</strong> · {hover.col.label} {hover.col.sub}: {pct(hover.v.rate)} —
      {hover.v.pass} pass, {hover.v.fail} fail, {hover.v.na} not applicable
    {:else}
      Hover or focus a cell for counts. Rate = pass / (pass + fail); n/a when the practice does not apply.
    {/if}
  </p>
  <div class="legend" aria-hidden="true">
    <span>0%</span>
    {#each [0.05, 0.2, 0.35, 0.5, 0.65, 0.8, 0.95] as r (r)}
      <i style:background={rampColor(r).fill}></i>
    {/each}
    <span>100%</span>
  </div>
</div>

<style>
  .heatmap { overflow-x: auto; }
  .grid { display: grid; gap: 2px; font-size: 0.8rem; }
  .corner, .colhead, .rowhead { color: var(--text-secondary); }
  .colhead { display: flex; flex-direction: column; justify-content: end; padding: 0.25rem; }
  .colhead small { color: var(--text-muted); }
  .rowhead { display: flex; align-items: center; padding-right: 0.5rem; }
  .rowhead a { color: var(--text-primary); text-decoration: none; }
  .rowhead a:hover { text-decoration: underline; }
  .cell {
    display: flex; align-items: center; justify-content: center;
    min-height: 2rem; border: 0; border-radius: 4px; font: inherit; font-variant-numeric: tabular-nums;
  }
  button.cell { cursor: default; }
  button.cell:focus-visible { outline: 2px solid var(--text-primary); outline-offset: 1px; }
  .empty { background: var(--neutral); color: var(--text-muted); }
  .tip { min-height: 1.5rem; margin: 0.5rem 0 0.25rem; color: var(--text-secondary); font-size: 0.85rem; }
  .legend { display: flex; align-items: center; gap: 2px; font-size: 0.75rem; color: var(--text-muted); }
  .legend i { width: 1.5rem; height: 0.6rem; border-radius: 2px; }
  .legend span { margin: 0 0.4rem; }
</style>
