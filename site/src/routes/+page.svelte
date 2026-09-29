<script>
  import { resolve } from '$app/paths';
  import ArmComparison from '$lib/ArmComparison.svelte';
  import Heatmap from '$lib/Heatmap.svelte';
  import TrialDetail from '$lib/TrialDetail.svelte';
  import { ci, pct, secs, usd } from '$lib/format.js';
  import { catalogOf, checksOf, view } from '$lib/runs.svelte.js';

  let { data } = $props();

  let run = $derived(view.run);
  let catalog = $derived(catalogOf(run, data.catalog));
  let checkDefs = $derived(checksOf(catalog));
  let titles = $derived(Object.fromEntries(checkDefs.map((c) => [c.id, c.title])));
  let armDefs = $derived(catalog?.arms ?? []);

  let chosenArm = $state('implicit');
  let trialCell = $state('');
  let trialTask = $state('');
  let expanded = $state('');

  let availableArms = $derived(
    run ? armDefs.map((a) => a.id).filter((a) => run.summary.cells.some((c) => c.arm === a)) : [],
  );
  // Fall back to the first arm present in this run when the chosen one is absent.
  let arm = $derived(availableArms.includes(chosenArm) ? chosenArm : (availableArms[0] ?? chosenArm));
  let armDef = $derived(armDefs.find((a) => a.id === arm));
  let cells = $derived(run ? run.summary.cells.filter((c) => c.arm === arm) : []);
  // Heatmap rows follow the catalog order; checks absent from the catalog are appended.
  let checkIds = $derived.by(() => {
    const present = new Set(cells.flatMap((c) => Object.keys(c.checks)));
    return [...checkDefs.map((c) => c.id).filter((id) => present.has(id)), ...[...present].filter((id) => !(id in titles)).sort()];
  });
  let columns = $derived(cells.map((c) => ({ key: c.cell, label: c.harness, sub: c.model.split('/').pop() })));
  let taskIds = $derived(run ? [...new Set(run.trials.map((t) => t.task))].sort() : []);
  let trials = $derived(
    run
      ? run.trials.filter(
          (t) => t.arm === arm && (!trialCell || t.cell === trialCell) && (!trialTask || t.task === trialTask),
        )
      : [],
  );
  let totalCost = $derived(run ? run.summary.cells.reduce((s, c) => s + (c.billed_cost_usd ?? 0), 0) : 0);

  const heatValue = (row, cellKey) => cells.find((c) => c.cell === cellKey)?.checks[row];
  const failing = (t) =>
    Object.entries(t.checks)
      .filter(([, c]) => c.status === 'fail')
      .map(([id]) => id);
  const key = (t) => `${t.shard}/${t.trial}`;
</script>

<h1>Results</h1>
<p class="lede">
  How well do coding agents × models follow container good practices with Podman, before any skill is installed?
  Each trial asks an agent to containerize (or repair) an app; a hidden grader rebuilds the result from scratch, runs
  it, probes it, and scores every practice. See <a href={resolve('/checks')}>checks</a>,
  <a href={resolve('/tasks')}>tasks</a> and <a href={resolve('/methodology')}>methodology</a>.
</p>

{#if !data.index?.runs?.length}
  <p class="notice">No benchmark run has been published yet.</p>
{:else if !run}
  <p class="notice">Loading…</p>
{:else}
  <div class="filters">
    <fieldset>
      <span>Prompt arm</span>
      {#each availableArms as a (a)}
        <label class="chip" class:active={arm === a} title={armDefs.find((d) => d.id === a)?.summary}>
          <input type="radio" name="arm" value={a} checked={arm === a} onchange={() => (chosenArm = a)} />
          {a}
        </label>
      {/each}
    </fieldset>
    <span class="meta">
      dataset v{run.dataset_version} · harbor {run.harbor_version} · billed {usd(totalCost)}
      {#if run.run_url}· <a href={run.run_url} rel="external noopener">CI run</a>{/if}
    </span>
  </div>
  {#if armDef}
    <p class="note"><strong>{arm}</strong>: {armDef.summary} {armDef.reading}</p>
  {/if}
  {#if run.status && run.status !== 'success'}
    <p class="notice">
      Partial run ({run.status}): {run.trials.length} of {run.n_planned ?? '?'} planned trials completed. Compare cells
      with care; the trial counts below differ.
    </p>
  {/if}

  <section>
    <h2>Leaderboard</h2>
    <div class="scroll">
      <table>
        <thead>
          <tr>
            <th>Harness</th>
            <th>Model</th>
            <th class="num" title="Trials graded / completed / planned (infra and budget failures are not graded)">Trials</th>
            <th class="num" title="All gates pass: artifact, build, start, probe. 95% Wilson interval.">Works</th>
            <th class="num" title="Weighted share of applicable practice checks passed (unconditional). 95% task-bootstrap interval.">Practice</th>
            <th class="num" title="OpenRouter per-key usage: the exact billed amount for this cell and arm">Billed</th>
            <th class="num" title="What the harness itself reported; often wrong for OpenRouter models">Harness says</th>
            <th class="num">$ / success</th>
            <th class="num" title="Mean agent wall time per trial">Agent time</th>
            <th class="num" title="Share of trials where the agent ran a docker command">Used docker</th>
            <th class="num" title="Share of trials where the agent itself ran podman build">Self-verified</th>
          </tr>
        </thead>
        <tbody>
          {#each [...cells].sort((a, b) => (b.practice_uncond_mean ?? -1) - (a.practice_uncond_mean ?? -1)) as c (c.cell)}
            <tr>
              <td>{c.harness}</td>
              <td class="mono">{c.model}</td>
              <td class="num">{c.n_valid}/{c.n_trials}{c.n_planned && c.n_planned !== c.n_trials ? `/${c.n_planned}` : ''}</td>
              <td class="num">{pct(c.gate_pass_rate)} <small>{ci(c.gate_pass_ci)}</small></td>
              <td class="num"><strong>{pct(c.practice_uncond_mean)}</strong> <small>{ci(c.practice_uncond_ci)}</small></td>
              <td class="num" title={c.unattributed_cost_usd ? `${usd(c.unattributed_cost_usd)} not attributable to a single trial` : ''}>{usd(c.billed_cost_usd)}</td>
              <td class="num muted">{usd(c.harness_reported_cost_usd)}</td>
              <td class="num">{usd(c.cost_per_success_usd)}</td>
              <td class="num">{secs(c.mean_agent_seconds)}</td>
              <td class="num">{pct(c.docker_usage_rate)}</td>
              <td class="num">{pct(c.self_built_rate)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    <p class="note">Small samples: intervals are wide. Differences inside overlapping intervals are not evidence of a real gap.</p>
  </section>

  <section>
    <h2>Practice gaps</h2>
    <p class="note">
      Pass rate of each graded practice, per harness × model, for the <strong>{arm}</strong> arm. Click a practice for its
      definition, how it is measured and example evidence.
    </p>
    {#if cells.length}
      <Heatmap rows={checkIds} {columns} value={heatValue} rowLabel={(id) => titles[id] ?? id} rowHref />
    {/if}
  </section>

  <section>
    <h2>Knowledge vs disposition</h2>
    <p class="note">
      The same check across prompt arms. A practice skipped in the implicit arm but applied when spelled out is a
      <strong>disposition gap</strong> (a short rule-style skill should fix it); one that fails even in the explicit arm is
      a <strong>knowledge gap</strong> (the skill needs reference material). Sorted by implicit pass rate.
    </p>
    <ArmComparison cells={run.summary.cells} armOrder={armDefs.map((a) => a.id)} checks={checkDefs} />
  </section>

  <section>
    <h2>Trials</h2>
    <div class="filters">
      <label>
        Cell
        <select bind:value={trialCell}>
          <option value="">all</option>
          {#each cells as c (c.cell)}<option value={c.cell}>{c.cell}</option>{/each}
        </select>
      </label>
      <label>
        Task
        <select bind:value={trialTask}>
          <option value="">all</option>
          {#each taskIds as t (t)}<option value={t}>{t}</option>{/each}
        </select>
      </label>
      <span class="meta">{trials.length} trials · click a row for every check's evidence</span>
    </div>
    <div class="scroll">
      <table>
        <thead>
          <tr>
            <th>Task</th><th>Cell</th><th>Outcome</th><th class="num">Practice</th><th class="num">Image</th>
            <th class="num">Billed</th><th class="num">Agent time</th><th>Failed checks</th>
          </tr>
        </thead>
        <tbody>
          {#each trials as t (key(t))}
            <tr class="trial" class:open={expanded === key(t)} onclick={() => (expanded = expanded === key(t) ? '' : key(t))}>
              <td>
                <button class="toggle" aria-expanded={expanded === key(t)} aria-label="Show trial details">
                  {expanded === key(t) ? '▾' : '▸'}
                </button>
                <a href={resolve('/tasks/[id]', { id: t.task })} onclick={(e) => e.stopPropagation()}>{t.task}</a>
              </td>
              <td class="mono">{t.cell}</td>
              <td>{t.failure_class === 'none' ? 'works' : t.failure_class}</td>
              <td class="num">{pct(t.practice_uncond)}</td>
              <td class="num">{t.image_size_mb ? `${Math.round(t.image_size_mb)} MB` : '–'}</td>
              <td class="num">{usd(t.cost_usd ?? t.metered?.billed_cost_usd)}</td>
              <td class="num">{secs(t.agent_seconds)}</td>
              <td class="failed">
                {#each failing(t) as id (id)}<span class="tag" title={t.checks[id].evidence}>{id}</span>{/each}
              </td>
            </tr>
            {#if expanded === key(t)}
              <tr class="expanded">
                <td colspan="8">
                  <TrialDetail
                    trial={t}
                    checks={checkDefs}
                    gates={catalog?.gates ?? []}
                    failureHelp={catalog?.failure_classes ?? {}}
                    runUrl={run.run_url}
                  />
                </td>
              </tr>
            {/if}
          {/each}
        </tbody>
      </table>
    </div>
  </section>
{/if}

<style>
  .filters fieldset span { margin-right: 0.2rem; }
  .failed { white-space: normal !important; }
  .trial { cursor: pointer; }
  .trial:hover, .trial.open { background: var(--neutral); }
  .expanded td { white-space: normal !important; }
  .toggle { border: 0; background: none; color: var(--text-secondary); cursor: pointer; padding: 0 0.3rem 0 0; font: inherit; }
</style>
