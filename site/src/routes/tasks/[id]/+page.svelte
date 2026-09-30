<script>
  import { page } from '$app/state';
  import { resolve } from '$app/paths';
  import { mean, pct, rampColor } from '$lib/format.js';
  import Inline from '$lib/Inline.svelte';
  import { currentCatalog, checksOf, gatesOf, view, versionNote } from '$lib/runs.svelte.js';

  let { data } = $props();

  let run = $derived(view.run);
  let catalog = $derived(currentCatalog(run, data.catalog));
  let note = $derived(versionNote(run, catalog));
  let tasks = $derived(catalog?.tasks ?? []);
  let selectedId = $derived(page.params.id);
  let task = $derived(tasks.find((t) => t.id === selectedId));
  let taskFamilies = $derived(task?.families ?? (task ? [task.family] : []));
  let taskChecks = $derived(checksOf(catalog, taskFamilies));
  let titles = $derived(Object.fromEntries(checksOf(catalog).map((c) => [c.id, c.title])));
  let gates = $derived(gatesOf(catalog, task?.gate ?? 'image'));
  let armDefs = $derived(catalog?.arms ?? []);
  let promptArm = $state('implicit');
  let prompt = $derived.by(() => {
    if (!task) return '';
    const extra = task.appended?.[promptArm] ?? armDefs.find((a) => a.id === promptArm)?.appended?.[task.family] ?? '';
    return extra ? `${task.instruction.trimEnd()}\n\n${extra}` : task.instruction;
  });

  let trials = $derived(run ? run.trials.filter((t) => t.task === selectedId) : []);
  let arms = $derived(armDefs.map((a) => a.id).filter((a) => trials.some((t) => t.arm === a)));
  let cellIds = $derived([...new Set(trials.map((t) => t.cell))].sort());
  const cellStat = (cell, arm) => {
    const ts = trials.filter((t) => t.cell === cell && t.arm === arm && !['infra', 'budget', 'no-verdict'].includes(t.failure_class));
    if (!ts.length) return null;
    return { n: ts.length, works: ts.filter((t) => t.reward === 1).length / ts.length, practice: mean(ts.map((t) => t.practice_uncond)) };
  };

  const size = (n) => (n > 1024 ? `${(n / 1024).toFixed(1)} KB` : `${n} B`);
</script>

<h1>Tasks</h1>
<p class="lede">
  The scenarios each agent is given. Everything below is generated from <code>tasks/&lt;id&gt;/</code> in the repository:
  the prompt, the app the agent starts from, and the reference solutions used to validate the grader.
</p>
{#if note}<p class="notice">{note}</p>{/if}

<div class="layout">
  <aside>
    <ul>
      {#each tasks as t (t.id)}
        <li>
          <a href={resolve('/tasks/[id]', { id: t.id })} aria-current={t.id === selectedId ? 'true' : undefined}>
            {t.id}<small>{t.spec.language} · {t.metadata.difficulty ?? ''}</small>
          </a>
        </li>
      {/each}
    </ul>
  </aside>

  {#if task}
    <article>
      <h2>{task.id}</h2>
      <p class="meta">
        graded on {taskFamilies.join(' + ')} · {task.spec.language} · {task.metadata.difficulty ?? 'n/a'} · agent timeout {task.timeouts.agent_sec}s
      </p>

      <h3>Prompt given to the agent</h3>
      <div class="filters">
        {#each armDefs as a (a.id)}
          <button class="chip" class:active={promptArm === a.id} onclick={() => (promptArm = a.id)} title={a.summary}>{a.id}</button>
        {/each}
      </div>
      <pre>{prompt}</pre>

      <h3>How "works" is decided</h3>
      <ol class="gates">
        {#each gates as g (g.id)}
          <li><strong>{g.title}</strong>: <Inline text={g.description} /></li>
        {/each}
      </ol>

      <h3>Grading spec</h3>
      <div class="scroll">
        <table>
          <tbody>
            <tr><th>App language</th><td>{task.spec.language ?? '–'}</td></tr>
            {#if task.spec.port}<tr><th>Listens on</th><td>port {task.spec.port}</td></tr>{/if}
            {#if task.spec.probe?.path}
              <tr><th>Probe</th><td><code>GET {task.spec.probe.path}</code> → {task.spec.probe.expect_status ?? 200}{task.spec.probe.expect_body ? `, body contains "${task.spec.probe.expect_body}"` : ''}</td></tr>
            {/if}
            {#if task.spec.run_args?.length}
              <tr><th>Run constraints</th><td class="wrap"><code>podman run {task.spec.run_args.join(' ')}</code></td></tr>
            {/if}
            {#if Object.keys(task.spec.run_env ?? {}).length}
              <tr><th>Run environment</th><td><code>{Object.entries(task.spec.run_env).map(([k, v]) => `${k}=${v}`).join(' ')}</code></td></tr>
            {/if}
            {#if taskFamilies.includes('containerfile')}
              <tr><th>Build step</th><td>{task.spec.needs_build ? 'yes (multi-stage applies)' : 'no (multi-stage is n/a)'}</td></tr>
              <tr><th>Image size budget</th><td>{task.spec.image_size_mb ? `${task.spec.image_size_mb} MB` : 'none'}</td></tr>
              <tr><th>Planted secret</th><td>{task.spec.canary_file ? `${task.spec.canary_file} with a canary value` : 'none'}</td></tr>
            {/if}
          </tbody>
        </table>
      </div>

      <h3>Checks graded on this task <small>({taskChecks.length})</small></h3>
      <p>{#each taskChecks as c (c.id)}<a class="tag" href={resolve('/checks/[id]', { id: c.id })}>{c.title}</a>{/each}</p>

      <h3>Starting files <small>({task.files.length})</small></h3>
      {#each task.files as f (f.path)}
        <details>
          <summary><span class="mono">{f.path}</span> <small>{size(f.size)}</small></summary>
          {#if f.content != null}<pre>{f.content}</pre>{:else}<p class="note">Content omitted (generated or large file).</p>{/if}
        </details>
      {/each}

      <h3>Reference solutions</h3>
      <p class="note">Graded in CI on every change: each must get exactly the expected result, so a check that rejects a valid
        strategy is caught before any agent runs. <code>best</code> is also Harbor's oracle agent.</p>
      {#each task.oracles as o (o.name)}
        <details>
          <summary>
            <strong>{o.name}</strong>
            <small>expected reward {o.expect.reward ?? '–'}{o.files.length ? '' : ' · no files (agent did nothing)'}</small>
          </summary>
          {#each Object.entries(o.expect.checks ?? {}) as [status, ids] (status)}
            <p class="expect"><span class={`status-${status}`}>{status}</span>:
              {#each ids as id (id)}<a class="tag" href={resolve('/checks/[id]', { id })}>{titles[id] ?? id}</a>{/each}
            </p>
          {/each}
          {#each o.files as f (f.path)}
            <p class="mono fname">{f.path}</p>
            {#if f.content != null}<pre>{f.content}</pre>{/if}
          {/each}
        </details>
      {/each}

      {#if run && trials.length}
        <h3>Results in the selected run</h3>
        <div class="scroll">
          <table>
            <thead><tr><th>Cell</th>{#each arms as a (a)}<th class="num">{a}: works / practice</th>{/each}</tr></thead>
            <tbody>
              {#each cellIds as cell (cell)}
                <tr>
                  <td class="mono">{cell}</td>
                  {#each arms as a (a)}
                    {@const s = cellStat(cell, a)}
                    {#if s}
                      {@const col = rampColor(s.practice ?? 0)}
                      <td class="num">
                        {pct(s.works)} /
                        <span class="pill" style:background={col.fill} style:color={col.ink}>{pct(s.practice)}</span>
                        <small>n={s.n}</small>
                      </td>
                    {:else}
                      <td class="num muted">–</td>
                    {/if}
                  {/each}
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
        <p class="note">Expand a trial on the <a href={resolve('/')}>results page</a> (filter by task) to see every check's evidence.</p>
      {/if}
    </article>
  {:else}
    <p class="notice">Unknown task.</p>
  {/if}
</div>

<style>
  .layout { display: grid; grid-template-columns: 16rem 1fr; gap: 2rem; align-items: start; }
  aside { position: sticky; top: 1rem; }
  aside ul { list-style: none; margin: 0; padding: 0; }
  aside li a { display: flex; flex-direction: column; padding: 0.3rem 0.5rem; border-radius: 4px; color: var(--text-secondary); text-decoration: none; }
  aside li a[aria-current='true'] { background: var(--neutral); color: var(--text-primary); font-weight: 600; }
  aside small { font-weight: 400; }
  article h2 { margin-top: 0.5rem; }
  details { margin: 0.25rem 0; background: var(--surface-1); border: 1px solid var(--rule); border-radius: 6px; padding: 0.4rem 0.75rem; }
  summary { cursor: pointer; }
  details pre { margin: 0.4rem 0; }
  .expect { margin: 0.35rem 0; font-size: 0.85rem; }
  .expect .tag { text-decoration: none; }
  .fname { margin: 0.6rem 0 0; }
  .pill { padding: 0 0.35rem; border-radius: 4px; }
  .gates li { margin: 0.2rem 0; }
  .wrap { white-space: normal !important; }
  p .tag { text-decoration: none; }
  th { width: 12rem; }
  @media (max-width: 800px) { .layout { grid-template-columns: 1fr; } aside { position: static; } }
</style>
