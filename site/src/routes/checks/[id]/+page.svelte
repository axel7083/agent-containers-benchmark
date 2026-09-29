<script>
  import Inline from '$lib/Inline.svelte';
  import { page } from '$app/state';
  import { resolve } from '$app/paths';
  import { pct, rampColor } from '$lib/format.js';
  import { catalogOf, checksOf, view } from '$lib/runs.svelte.js';

  let { data } = $props();

  let run = $derived(view.run);
  let catalog = $derived(catalogOf(run, data.catalog));
  let checks = $derived(checksOf(catalog));
  let selectedId = $derived(page.params.id);
  let check = $derived(checks.find((c) => c.id === selectedId));
  let categories = $derived([...new Set(checks.map((c) => c.category))]);
  let arms = $derived((catalog?.arms ?? []).map((a) => a.id).filter((a) => run?.summary.cells.some((c) => c.arm === a)));
  let cellIds = $derived(run ? [...new Set(run.summary.cells.map((c) => c.cell))] : []);

  const stat = (cell, arm) => run?.summary.cells.find((c) => c.cell === cell && c.arm === arm)?.checks[selectedId];

  // Most frequent failure evidence for this check, with the cells it appeared in.
  let evidence = $derived.by(() => {
    if (!run || !check) return [];
    const groups = {};
    for (const t of run.trials) {
      const r = t.checks[selectedId];
      if (!r || r.status !== 'fail' || t.failure_class === 'no-artifact') continue;
      const g = (groups[r.evidence] ??= { text: r.evidence, count: 0, cells: [] });
      g.count += 1;
      if (!g.cells.includes(t.cell)) g.cells.push(t.cell);
    }
    return Object.values(groups).sort((a, b) => b.count - a.count).slice(0, 12);
  });

  let perTask = $derived.by(() => {
    if (!run) return [];
    const tasks = {};
    for (const t of run.trials) {
      const r = t.checks[selectedId];
      if (!r || t.failure_class === 'no-artifact') continue;
      tasks[t.task] ??= { pass: 0, fail: 0, na: 0 };
      if (r.status in tasks[t.task]) tasks[t.task][r.status] += 1;
    }
    return Object.entries(tasks).sort();
  });

</script>

<h1>Checks</h1>
<p class="lede">
  Every practice the hidden grader scores. Definitions come straight from the grader source; the rule text is also,
  verbatim, what the <em>explicit</em> prompt arm appends.
</p>

<div class="layout">
  <aside>
    {#each categories as cat (cat)}
      <h3>{cat}</h3>
      <ul>
        {#each checks.filter((c) => c.category === cat) as c (c.id)}
          <li><a href={resolve('/checks/[id]', { id: c.id })} aria-current={c.id === selectedId ? 'true' : undefined}>{c.title}</a></li>
        {/each}
      </ul>
    {/each}
  </aside>

  {#if check}
    <article>
      <h2>{check.title} <small class="mono">{check.id}</small></h2>
      <p class="meta">
        {check.category} · weight {check.weight}{check.informational ? ' (informational, not scored)' : ''}
      </p>

      <h3>Rule (as written in the explicit prompt)</h3>
      <blockquote><Inline text={check.rule} /></blockquote>

      <h3>Why it matters</h3>
      <p><Inline text={check.why} /></p>

      <h3>How it is measured</h3>
      <p><Inline text={check.how} /></p>

      <h3>Accepted strategies</h3>
      <p>{#each check.accepted as a (a)}<span class="tag">{a}</span>{/each}</p>

      {#if check.not_applicable}
        <h3>Not applicable when</h3>
        <p><Inline text={check.not_applicable} /></p>
      {/if}

      {#if run}
        <h3>Pass rate in the selected run</h3>
        <p class="note">Trials where the agent produced no Containerfile are left out: they score 0 on practice, but say
          nothing about this check.</p>
        <div class="scroll">
          <table>
            <thead><tr><th>Cell</th>{#each arms as a (a)}<th class="num">{a}</th>{/each}</tr></thead>
            <tbody>
              {#each cellIds as cell (cell)}
                <tr>
                  <td class="mono">{cell}</td>
                  {#each arms as a (a)}
                    {@const s = stat(cell, a)}
                    {#if s && s.rate != null}
                      {@const col = rampColor(s.rate)}
                      <td class="num rate" style:background={col.fill} style:color={col.ink} title={`${s.pass} pass, ${s.fail} fail, ${s.na} n/a`}>
                        {pct(s.rate)} <small style:color={col.ink}>n={s.pass + s.fail}</small>
                      </td>
                    {:else}
                      <td class="num muted">n/a</td>
                    {/if}
                  {/each}
                </tr>
              {/each}
            </tbody>
          </table>
        </div>

        <h3>By task (all cells and arms)</h3>
        <div class="scroll">
          <table>
            <thead><tr><th>Task</th><th class="num">pass</th><th class="num">fail</th><th class="num">n/a</th><th class="num">rate</th></tr></thead>
            <tbody>
              {#each perTask as [task, s] (task)}
                <tr>
                  <td><a href={resolve('/tasks/[id]', { id: task })}>{task}</a></td>
                  <td class="num">{s.pass}</td><td class="num">{s.fail}</td><td class="num">{s.na}</td>
                  <td class="num">{s.pass + s.fail ? pct(s.pass / (s.pass + s.fail)) : 'n/a'}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>

        <h3>Most common failure evidence</h3>
        {#if evidence.length}
          <div class="scroll">
            <table>
              <thead><tr><th class="num">Trials</th><th>Evidence</th><th>Cells</th></tr></thead>
              <tbody>
                {#each evidence as e (e.text)}
                  <tr>
                    <td class="num">{e.count}</td>
                    <td class="evidence">{e.text}</td>
                    <td class="cells">{#each e.cells as c (c)}<span class="tag">{c}</span>{/each}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {:else}
          <p class="note">No failure recorded for this check in the selected run.</p>
        {/if}
      {/if}
    </article>
  {:else}
    <p class="notice">Unknown check.</p>
  {/if}
</div>

<style>
  .layout { display: grid; grid-template-columns: 15rem 1fr; gap: 2rem; align-items: start; }
  aside { position: sticky; top: 1rem; }
  aside h3 { margin: 0.75rem 0 0.25rem; font-size: 0.8rem; text-transform: uppercase; color: var(--text-muted); letter-spacing: 0.04em; }
  aside ul { list-style: none; margin: 0; padding: 0; }
  aside li a { display: block; padding: 0.15rem 0.4rem; border-radius: 4px; color: var(--text-secondary); text-decoration: none; font-size: 0.9rem; }
  aside li a[aria-current='true'] { background: var(--neutral); color: var(--text-primary); font-weight: 600; }
  article h2 { margin-top: 0.5rem; }
  article h2 small { font-weight: 400; margin-left: 0.4rem; }
  blockquote { margin: 0; padding: 0.5rem 0.75rem; border-left: 3px solid var(--accent); background: var(--surface-1); }
  .rate { border-radius: 4px; }
  .evidence { font-family: var(--mono); font-size: 0.75rem; white-space: pre-wrap !important; word-break: break-word; }
  .cells { white-space: normal !important; }
  @media (max-width: 800px) { .layout { grid-template-columns: 1fr; } aside { position: static; } }
</style>
