<script>
  import Inline from './Inline.svelte';
  import { resolve } from '$app/paths';
  import { pct, secs, usd } from './format.js';

  /** @type {{ trial: any, checks: any[], gates: any[], failureHelp: Record<string, string>, runUrl?: string }} */
  let { trial, checks, gates, failureHelp, runUrl } = $props();

  let rows = $derived(
    checks.map((c) => ({ ...c, result: trial.checks[c.id] ?? { status: 'na', evidence: 'not evaluated' } })),
  );
  const gateState = (id) => (trial.gates[id] == null ? 'na' : trial.gates[id] === 1 ? 'pass' : 'fail');
</script>

<div class="detail">
  <div class="facts">
    <span><strong>{trial.failure_class === 'none' ? 'Works' : trial.failure_class}</strong>
      <small><Inline text={failureHelp[trial.failure_class] ?? ''} /></small></span>
    <span>Practice {pct(trial.practice_uncond)}</span>
    <span>Image {trial.image_size_mb ? `${Math.round(trial.image_size_mb)} MB` : '–'}</span>
    <span>Agent {secs(trial.agent_seconds)} · {trial.process?.steps ?? '–'} steps · {trial.process?.tool_calls ?? '–'} tool calls</span>
    <span>podman cmds {trial.process?.podman_commands ?? '–'} · docker cmds {trial.process?.docker_commands ?? '–'}
      · self-built {trial.process?.self_built ? 'yes' : 'no'}</span>
    <span>Billed {usd(trial.cost_usd ?? trial.metered?.billed_cost_usd)} (harness said {usd(trial.harness_reported?.cost_usd)})
      · {trial.metered?.requests ?? '–'} requests · providers {(trial.metered?.providers ?? []).join(', ') || '–'}</span>
    <span class="muted">{trial.harness} {trial.harness_version} · {trial.model} · {trial.trial}
      {#if runUrl}· <a href={runUrl} rel="external noopener">artifacts (CI run)</a>{/if}</span>
  </div>

  <div class="gates">
    {#each gates as g (g.id)}
      <span class={`tag status-${gateState(g.id)}`} title={g.description}>{g.title}: {gateState(g.id)}</span>
    {/each}
  </div>

  <table>
    <thead><tr><th>Check</th><th>Result</th><th>Evidence</th></tr></thead>
    <tbody>
      {#each rows as r (r.id)}
        <tr>
          <td><a href={resolve('/checks/[id]', { id: r.id })}>{r.title}</a>{#if r.informational} <small>(info)</small>{/if}</td>
          <td class={`status-${r.result.status}`}>{r.result.status}</td>
          <td class="evidence">{r.result.evidence}</td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>

<style>
  .detail { padding: 0.5rem 0.25rem 1rem; white-space: normal; }
  .facts { display: flex; flex-wrap: wrap; gap: 0.35rem 1.25rem; font-size: 0.85rem; margin-bottom: 0.5rem; }
  .gates { margin: 0.25rem 0 0.5rem; }
  table { border-collapse: collapse; font-size: 0.8rem; width: 100%; }
  th, td { text-align: left; padding: 0.25rem 0.5rem; border-bottom: 1px solid var(--rule); vertical-align: top; }
  th { color: var(--text-secondary); }
  .evidence { font-family: var(--mono); font-size: 0.75rem; white-space: pre-wrap; word-break: break-word; color: var(--text-secondary); }
</style>
