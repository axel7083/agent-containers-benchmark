<script>
  import { resolve } from '$app/paths';
  import { mean, pct } from '$lib/format.js';
  import { currentCatalog, view, versionNote } from '$lib/runs.svelte.js';

  let { data } = $props();

  let run = $derived(view.run);
  let catalog = $derived(currentCatalog(run, data.catalog));
  let note = $derived(versionNote(run, catalog));
  let tasks = $derived(catalog?.tasks ?? []);
  const EXCLUDED = ['infra', 'budget', 'no-verdict'];

  function stats(id) {
    const ts = (run?.trials ?? []).filter((t) => t.task === id && !EXCLUDED.includes(t.failure_class));
    if (!ts.length) return null;
    return { n: ts.length, works: ts.filter((t) => t.reward === 1).length / ts.length, practice: mean(ts.map((t) => t.practice_uncond)) };
  }
</script>

<h1>Tasks</h1>
<p class="lede">
  The scenarios agents are given, generated from <code>tasks/&lt;id&gt;/</code>. Open one for its exact prompt under each
  arm, the files the agent starts from, and the reference solutions that validate the grader.
</p>
{#if note}<p class="notice">{note}</p>{/if}

<div class="scroll">
  <table>
    <thead>
      <tr>
        <th>Task</th><th>Graded on</th><th>Language</th><th>Difficulty</th><th>Instruction</th>
        <th class="num" title="All arms and cells of the selected run">Works</th><th class="num">Practice</th><th class="num">Trials</th>
      </tr>
    </thead>
    <tbody>
      {#each tasks as t (t.id)}
        {@const s = stats(t.id)}
        <tr>
          <td><a href={resolve('/tasks/[id]', { id: t.id })}>{t.id}</a></td>
          <td>{(t.families ?? [t.family]).join(' + ')}</td>
          <td>{t.spec.language}</td>
          <td>{t.metadata.difficulty ?? '–'}</td>
          <td class="instruction">{t.instruction.split('\n')[0]}</td>
          <td class="num">{pct(s?.works)}</td>
          <td class="num">{pct(s?.practice)}</td>
          <td class="num">{s?.n ?? 0}</td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>

<style>
  .instruction { white-space: normal !important; max-width: 40rem; color: var(--text-secondary); }
</style>
