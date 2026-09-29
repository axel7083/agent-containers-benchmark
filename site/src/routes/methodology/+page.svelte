<script>
  import Inline from '$lib/Inline.svelte';
  import { resolve } from '$app/paths';
  import { catalogOf, checksOf, view } from '$lib/runs.svelte.js';

  let { data } = $props();

  let catalog = $derived(catalogOf(view.run, data.catalog));
  let families = $derived(Object.keys(catalog?.families ?? {}));
  let scored = $derived(checksOf(catalog).filter((c) => !c.informational));
</script>

<h1>Methodology</h1>
<p class="lede">
  One <strong>trial</strong> = one agent (harness × model) given one <a href={resolve('/tasks')}>task</a> under one
  prompt arm, working unattended in a sandbox (Fedora, Podman, no Docker). When it stops, a hidden grader, copied into the
  sandbox only after the agent is done, judges the result.
</p>

{#if catalog}
  <h2>Prompt arms</h2>
  <p class="note">
    The same task is run under each arm; only the text appended to the task's instruction changes. Comparing arms tells
    whether a gap comes from disposition or missing knowledge, which decides what kind of skill would help.
  </p>
  <div class="scroll">
    <table>
      <thead><tr><th>Arm</th><th>What the agent gets</th><th>How to read it</th></tr></thead>
      <tbody>
        {#each catalog.arms as a (a.id)}
          <tr><td><strong>{a.id}</strong></td><td class="wrap">{a.summary}</td><td class="wrap">{a.reading}</td></tr>
        {/each}
      </tbody>
    </table>
  </div>
  {#each catalog.arms as a (a.id)}
    {#each families as f (f)}
      {#if a.appended[f]}
        <h3>Text appended in the <em>{a.id}</em> arm{families.length > 1 ? ` (${f})` : ''}</h3>
        <pre>{a.appended[f]}</pre>
      {/if}
    {/each}
  {/each}

  <h2>Gates: did it work?</h2>
  <p class="note">Evaluated in order; the first failing gate is the trial's outcome. "Works" means all gates passed.</p>
  <ol class="gates">
    {#each catalog.gates as g (g.id)}
      <li><strong>{g.title}</strong>: <Inline text={g.description} /></li>
    {/each}
  </ol>

  <h3>Outcomes</h3>
  <div class="scroll">
    <table>
      <tbody>
        {#each Object.entries(catalog.failure_classes) as [k, v] (k)}
          <tr><td class="mono">{k}</td><td class="wrap"><Inline text={v} /></td></tr>
        {/each}
      </tbody>
    </table>
  </div>

  <h2>Practice score: is it good?</h2>
  <p>
    {scored.length} weighted <a href={resolve('/checks')}>checks</a> each answer <em>pass</em>, <em>fail</em> or
    <em>n/a</em> (the practice does not apply to this task). The practice score is the weighted share of applicable
    checks that pass. It is computed whenever an artifact exists, even if a gate failed, so a model that only succeeds on
    easy tasks cannot look better than one that attempts everything. Every check lists the strategies it accepts, so a
    valid alternative (distroless vs minimal base, <code>.dockerignore</code> vs <code>.containerignore</code>) is never
    penalised.
  </p>

  <h2>Process metrics</h2>
  <p>
    Read from the agent's transcript (ATIF trajectory): number of steps and tool calls, whether it ran
    <code>docker</code> or <code>podman</code> commands, and whether it built its own image to check its work
    ("self-verified").
  </p>

  <h2>Cost</h2>
  <p>
    Every shard (one CI job: a harness × model × arm, split by task by default so up to 20 jobs run at once, each
    running its trials one after another) gets its own OpenRouter key with a spending cap. The key's usage is the exact
    billed amount and is the cost of record. A metering proxy between the agent and OpenRouter splits it across trials
    (per-generation cost) and forces the model under test; spend it cannot attribute to a trial (e.g. a request the agent
    cancelled mid-stream) is shown as unattributed. Harness-reported costs are displayed for comparison only: they are
    often far off for models served through OpenRouter.
  </p>

  <h2>Statistics</h2>
  <p>
    Pass rates carry a 95% Wilson interval. Practice scores carry a 95% bootstrap interval that resamples
    <em>tasks</em>, not trials, because trials of the same task are correlated. Trials lost to infrastructure problems or
    budget caps are excluded, never counted as failures. With few tasks the intervals are wide: treat differences inside
    overlapping intervals as noise.
  </p>

  <h2>Cells in the matrix</h2>
  <div class="scroll">
    <table>
      <thead><tr><th>Cell</th><th>Harness</th><th>Version</th><th>Model (OpenRouter)</th></tr></thead>
      <tbody>
        {#each catalog.cells as c (c.id)}
          <tr><td class="mono">{c.id}</td><td>{c.harness}</td><td class="mono">{c.version}</td><td class="mono">{c.model}</td></tr>
        {/each}
      </tbody>
    </table>
  </div>
  <p class="note">dataset v{catalog.dataset_version} · harbor {catalog.harbor_version}</p>
{:else}
  <p class="notice">The benchmark catalog has not been published yet.</p>
{/if}

<style>
  .wrap { white-space: normal !important; }
  .gates li { margin: 0.3rem 0; }
  p { max-width: 70rem; }
</style>
