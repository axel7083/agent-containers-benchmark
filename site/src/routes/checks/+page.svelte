<script>
  import Inline from '$lib/Inline.svelte';
  import { resolve } from '$app/paths';
  import { pct, rampColor } from '$lib/format.js';
  import { currentCatalog, checksOf, view, versionNote } from '$lib/runs.svelte.js';

  let { data } = $props();

  let run = $derived(view.run);
  let catalog = $derived(currentCatalog(run, data.catalog));
  let note = $derived(versionNote(run, catalog));
  let checks = $derived(checksOf(catalog));
  let arms = $derived((catalog?.arms ?? []).map((a) => a.id).filter((a) => run?.summary.cells.some((c) => c.arm === a)));

  // Pass rate of a check in one arm, pooled over every cell of the selected run.
  function pooled(id, arm) {
    let pass = 0;
    let fail = 0;
    for (const c of run?.summary.cells ?? []) {
      if (c.arm !== arm || !c.checks[id]) continue;
      pass += c.checks[id].pass;
      fail += c.checks[id].fail;
    }
    return pass + fail ? pass / (pass + fail) : null;
  }
</script>

<h1>Checks</h1>
<p class="lede">
  Every practice the hidden grader scores, generated from the grader source. The rule text is, verbatim, what the
  <em>explicit</em> prompt arm appends. Pass rates are pooled over every harness × model of the selected run.
</p>
{#if note}<p class="notice">{note}</p>{/if}

<div class="scroll">
  <table>
    <thead>
      <tr>
        <th>Check</th><th>Family</th><th>Category</th><th class="num">Weight</th><th>Rule</th>
        {#each arms as a (a)}<th class="num">{a}</th>{/each}
      </tr>
    </thead>
    <tbody>
      {#each checks as c (c.id)}
        <tr>
          <td><a href={resolve('/checks/[id]', { id: c.id })}>{c.title}</a><br /><small class="mono">{c.id}</small></td>
          <td>{c.family}</td>
          <td>{c.category}</td>
          <td class="num">{c.informational ? 'info' : c.weight}</td>
          <td class="rule"><Inline text={c.rule} /></td>
          {#each arms as a (a)}
            {@const r = pooled(c.id, a)}
            {#if r == null}
              <td class="num muted">n/a</td>
            {:else}
              {@const col = rampColor(r)}
              <td class="num"><span class="pill" style:background={col.fill} style:color={col.ink}>{pct(r)}</span></td>
            {/if}
          {/each}
        </tr>
      {/each}
    </tbody>
  </table>
</div>

<style>
  .rule { white-space: normal !important; max-width: 36rem; color: var(--text-secondary); }
  .pill { display: inline-block; min-width: 3rem; padding: 0.1rem 0.35rem; border-radius: 4px; text-align: center; }
</style>
