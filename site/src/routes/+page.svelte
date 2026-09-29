<script>
  import { base } from '$app/paths';
  import ArmComparison from '$lib/ArmComparison.svelte';
  import Heatmap from '$lib/Heatmap.svelte';
  import { ARMS, ARM_HELP, ci, pct, secs, usd } from '$lib/format.js';

  let { data } = $props();

  let index = $derived(data.index);
  let loaded = $state(null);
  let run = $derived(loaded ?? data.latest);
  let chosenFile = $state('');
  let runFile = $derived(chosenFile || (data.index?.runs?.[0]?.file ?? ''));
  let chosenArm = $state('implicit');
  let trialCell = $state('');
  let loadError = $state('');
  let error = $derived(data.error || loadError);

  async function selectRun(event) {
    chosenFile = event.currentTarget.value;
    try {
      const res = await fetch(`${base}/data/${chosenFile}`);
      if (!res.ok) throw new Error(`${chosenFile}: HTTP ${res.status}`);
      loaded = await res.json();
      trialCell = '';
    } catch (e) {
      loadError = String(e);
    }
  }

  let availableArms = $derived(run ? ARMS.filter((a) => run.summary.cells.some((c) => c.arm === a)) : []);
  // Fall back to the first arm present in this run when the chosen one is absent.
  let arm = $derived(availableArms.includes(chosenArm) ? chosenArm : (availableArms[0] ?? chosenArm));
  let cells = $derived(run ? run.summary.cells.filter((c) => c.arm === arm) : []);
  let checkIds = $derived([...new Set(cells.flatMap((c) => Object.keys(c.checks)))].sort());
  let columns = $derived(cells.map((c) => ({ key: c.cell, label: c.harness, sub: c.model.split('/').pop() })));
  let trials = $derived(
    run ? run.trials.filter((t) => t.arm === arm && (!trialCell || t.cell === trialCell)) : [],
  );
  let totalCost = $derived(run ? run.summary.cells.reduce((s, c) => s + (c.billed_cost_usd ?? 0), 0) : 0);

  function heatValue(row, cellKey) {
    return cells.find((c) => c.cell === cellKey)?.checks[row];
  }

  const failing = (t) =>
    Object.entries(t.checks)
      .filter(([, c]) => c.status === 'fail')
      .map(([id]) => id);
</script>

<header>
  <h1>agent-containers-benchmark</h1>
  <p class="lede">
    How well do coding agents × models follow container good practices with Podman, before any skill is
    installed? Each trial asks an agent to containerize (or repair) an app; a hidden grader rebuilds the
    result from scratch, runs it, probes it, and scores every practice.
    <a href="https://github.com/axel7083/agent-containers-benchmark" rel="external noopener">Source &amp; methodology</a>.
  </p>
</header>

{#if error}
  <p class="notice">Could not load results: {error}</p>
{:else if !index}
  <p class="notice">Loading…</p>
{:else if !index.runs.length}
  <p class="notice">No benchmark run has been published yet.</p>
{:else}
  <div class="filters">
    <label>
      Run
      <select value={runFile} onchange={selectRun}>
        {#each index.runs as r (r.file)}
          <option value={r.file}>
            {r.created_at?.slice(0, 16).replace('T', ' ')} · {r.n_trials}{r.n_planned ? `/${r.n_planned}` : ''} trials
            · {usd(r.billed_cost_usd)}{r.status && r.status !== 'success' ? ` · ${r.status}` : ''}
          </option>
        {/each}
      </select>
    </label>
    <fieldset>
      <legend>Prompt arm</legend>
      {#each availableArms as a (a)}
        <label class="chip" class:active={arm === a} title={ARM_HELP[a]}>
          <input type="radio" name="arm" value={a} checked={arm === a} onchange={() => (chosenArm = a)} />
          {a}
        </label>
      {/each}
    </fieldset>
    {#if run}
      <span class="meta">
        dataset v{run.dataset_version} · harbor {run.harbor_version} · billed {usd(totalCost)}
        {#if run.run_url}· <a href={run.run_url} rel="external noopener">CI run</a>{/if}
      </span>
    {/if}
  </div>
  {#if run && run.status && run.status !== 'success'}
    <p class="notice partial">
      Partial run ({run.status}): {run.trials.length} of {run.n_planned ?? '?'} planned trials completed. Compare cells
      with care; the trial counts below differ.
    </p>
  {/if}
  <p class="armhelp"><strong>{arm}</strong>: {ARM_HELP[arm]}</p>

  {#if run}
    <section>
      <h2>Leaderboard</h2>
      <div class="scroll">
        <table>
          <thead>
            <tr>
              <th>Harness</th>
              <th>Model</th>
              <th class="num" title="Trials graded / completed / planned (infra and budget failures are not graded)">Trials</th>
              <th class="num" title="Build, start and HTTP probe all pass. 95% Wilson interval.">Works</th>
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
                <td class="num" title={c.unattributed_cost_usd ? `${usd(c.unattributed_cost_usd)} not attributable to a single trial (e.g. requests cancelled mid-stream)` : ''}>{usd(c.billed_cost_usd)}</td>
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
      <p class="note">
        Small samples: intervals are wide. Differences inside overlapping intervals are not evidence of a real gap.
      </p>
    </section>

    <section>
      <h2>Practice gaps</h2>
      <p class="note">Pass rate of each graded practice, per harness × model, for the <strong>{arm}</strong> arm.
        Low cells in the implicit arm that rise in the explicit arm are what a skill should teach.</p>
      {#if cells.length}
        <Heatmap rows={checkIds} {columns} value={heatValue} />
      {/if}
    </section>

    <section>
      <h2>Knowledge vs disposition</h2>
      <p class="note">
        The same check across prompt arms. A practice skipped in the implicit arm but applied when spelled out is a
        <strong>disposition gap</strong> (a short rule-style skill should fix it); one that fails even in the explicit arm
        is a <strong>knowledge gap</strong> (the skill needs reference material). Sorted by implicit pass rate.
      </p>
      <ArmComparison cells={run.summary.cells} />
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
            {#each trials as t (t.trial + t.shard)}
              <tr>
                <td>{t.task}</td>
                <td class="mono">{t.cell}</td>
                <td>{t.failure_class === 'none' ? 'works' : t.failure_class}</td>
                <td class="num">{pct(t.practice_uncond)}</td>
                <td class="num">{t.image_size_mb ? `${Math.round(t.image_size_mb)} MB` : '–'}</td>
                <td class="num">{usd(t.cost_usd ?? t.metered?.billed_cost_usd)}</td>
                <td class="num">{secs(t.agent_seconds)}</td>
                <td class="failed">
                  {#each failing(t) as id (id)}<span title={t.checks[id].evidence}>{id}</span>{/each}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </section>
  {/if}
{/if}

<style>
  h1 { margin: 0 0 0.25rem; font-size: 1.6rem; }
  h2 { margin: 2rem 0 0.5rem; font-size: 1.15rem; }
  .lede { max-width: 60rem; color: var(--text-secondary); }
  .partial { margin: 0.5rem 0; }
  .notice { padding: 1rem; background: var(--surface-1); border: 1px solid var(--rule); border-radius: 6px; }
  .filters { display: flex; flex-wrap: wrap; align-items: center; gap: 1rem; margin: 1rem 0 0.25rem; }
  .filters label, fieldset { display: flex; align-items: center; gap: 0.4rem; color: var(--text-secondary); font-size: 0.9rem; }
  fieldset { border: 0; padding: 0; margin: 0; }
  legend { float: left; margin-right: 0.4rem; }
  select { font: inherit; padding: 0.2rem 0.4rem; background: var(--surface-1); color: var(--text-primary); border: 1px solid var(--rule); border-radius: 4px; }
  .chip { padding: 0.15rem 0.6rem; border: 1px solid var(--rule); border-radius: 999px; cursor: pointer; }
  .chip input { position: absolute; opacity: 0; pointer-events: none; }
  .chip.active { border-color: var(--accent); color: var(--text-primary); }
  .chip:focus-within { outline: 2px solid var(--accent); }
  .meta, .armhelp, .note { color: var(--text-muted); font-size: 0.85rem; }
  .scroll { overflow-x: auto; background: var(--surface-1); border: 1px solid var(--rule); border-radius: 6px; }
  table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
  th, td { padding: 0.45rem 0.6rem; text-align: left; border-bottom: 1px solid var(--rule); white-space: nowrap; }
  th { color: var(--text-secondary); font-weight: 600; }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  small, .muted { color: var(--text-muted); }
  .mono { font-family: var(--mono); font-size: 0.8rem; }
  .failed { white-space: normal; }
  .failed span { display: inline-block; margin: 0 0.3rem 0.2rem 0; padding: 0 0.35rem; border: 1px solid var(--rule); border-radius: 4px; font-family: var(--mono); font-size: 0.75rem; }
</style>
