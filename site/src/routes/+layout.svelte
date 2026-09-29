<script>
  import { page } from '$app/state';
  import { resolve } from '$app/paths';
  import { selectRun, view } from '$lib/runs.svelte.js';
  import { usd } from '$lib/format.js';

  let { data, children } = $props();

  const current = (path) => (page.url.pathname.startsWith(path) ? 'page' : undefined);
  let runs = $derived(data.index?.runs ?? []);
</script>

<header class="top">
  <a class="brand" href={resolve('/')}>agent-containers-benchmark</a>
  <nav>
    <a href={resolve('/')} aria-current={page.url.pathname === resolve('/') ? 'page' : undefined}>Results</a>
    <a href={resolve('/checks')} aria-current={current(resolve('/checks'))}>Checks</a>
    <a href={resolve('/tasks')} aria-current={current(resolve('/tasks'))}>Tasks</a>
    <a href={resolve('/methodology')} aria-current={current(resolve('/methodology'))}>Methodology</a>
    <a href="https://github.com/axel7083/agent-containers-benchmark" rel="external noopener">Source</a>
  </nav>
  {#if runs.length}
    <label class="runpick">
      Run
      <select value={view.file} onchange={(e) => selectRun(e.currentTarget.value)}>
        {#each runs as r (r.file)}
          <option value={r.file}>
            {r.created_at?.slice(0, 16).replace('T', ' ')} · {r.n_trials}{r.n_planned ? `/${r.n_planned}` : ''} trials
            · {usd(r.billed_cost_usd)}{r.status && r.status !== 'success' ? ` · ${r.status}` : ''}
          </option>
        {/each}
      </select>
    </label>
  {/if}
</header>

<main class="page">
  {#if data.error || view.error}
    <p class="notice">Could not load results: {data.error || view.error}</p>
  {/if}
  {@render children()}
</main>

<style>
  :global(:root) {
    color-scheme: light;
    --surface-1: #fcfcfb;
    --page: #f9f9f7;
    --text-primary: #0b0b0b;
    --text-secondary: #52514e;
    --text-muted: #6f6e69;
    --rule: #e4e3de;
    --neutral: #f0efec;
    --accent: #2a78d6;
    --good: #0ca30c;
    --critical: #d03b3b;
    --mono: ui-monospace, 'SFMono-Regular', Menlo, monospace;
  }
  @media (prefers-color-scheme: dark) {
    :global(:root) {
      color-scheme: dark;
      --surface-1: #1a1a19;
      --page: #0d0d0d;
      --text-primary: #ffffff;
      --text-secondary: #c3c2b7;
      --text-muted: #9a9990;
      --rule: #33332f;
      --neutral: #383835;
      --accent: #3987e5;
    }
  }
  :global(body) {
    margin: 0;
    background: var(--page);
    color: var(--text-primary);
    font: 15px/1.5 system-ui, -apple-system, 'Segoe UI', sans-serif;
  }
  :global(a) { color: var(--accent); }
  :global(h1) { margin: 0.5rem 0 0.25rem; font-size: 1.5rem; }
  :global(h2) { margin: 2rem 0 0.5rem; font-size: 1.15rem; }
  :global(h3) { margin: 1.25rem 0 0.4rem; font-size: 1rem; }
  :global(code) { font-family: var(--mono); font-size: 0.85em; padding: 0 0.2em; background: var(--neutral); border-radius: 3px; }
  :global(pre) { font-family: var(--mono); font-size: 0.8rem; background: var(--surface-1); border: 1px solid var(--rule); border-radius: 6px; padding: 0.75rem; overflow-x: auto; white-space: pre-wrap; }
  :global(.lede), :global(.note), :global(.meta) { color: var(--text-muted); font-size: 0.9rem; max-width: 70rem; }
  :global(.lede) { color: var(--text-secondary); font-size: 1rem; }
  :global(.notice) { padding: 0.75rem 1rem; background: var(--surface-1); border: 1px solid var(--rule); border-radius: 6px; }
  :global(.filters) { display: flex; flex-wrap: wrap; align-items: center; gap: 1rem; margin: 1rem 0 0.25rem; }
  :global(.filters label), :global(.filters fieldset) { display: flex; align-items: center; gap: 0.4rem; color: var(--text-secondary); font-size: 0.9rem; border: 0; padding: 0; margin: 0; }
  :global(select) { font: inherit; padding: 0.2rem 0.4rem; background: var(--surface-1); color: var(--text-primary); border: 1px solid var(--rule); border-radius: 4px; }
  :global(.chip) { display: inline-block; padding: 0.1rem 0.6rem; border: 1px solid var(--rule); border-radius: 999px; cursor: pointer; font-size: 0.85rem; color: var(--text-secondary); background: none; font-family: inherit; }
  :global(.chip input) { position: absolute; opacity: 0; pointer-events: none; }
  :global(.chip.active) { border-color: var(--accent); color: var(--text-primary); }
  :global(.chip:focus-within) { outline: 2px solid var(--accent); }
  :global(.scroll) { overflow-x: auto; background: var(--surface-1); border: 1px solid var(--rule); border-radius: 6px; }
  :global(.scroll table) { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
  :global(.scroll th), :global(.scroll td) { padding: 0.45rem 0.6rem; text-align: left; border-bottom: 1px solid var(--rule); white-space: nowrap; vertical-align: top; }
  :global(.scroll th) { color: var(--text-secondary); font-weight: 600; }
  :global(.num) { text-align: right !important; font-variant-numeric: tabular-nums; }
  :global(small), :global(.muted) { color: var(--text-muted); }
  :global(.mono) { font-family: var(--mono); font-size: 0.8rem; }
  :global(.tag) { display: inline-block; margin: 0 0.3rem 0.2rem 0; padding: 0 0.35rem; border: 1px solid var(--rule); border-radius: 4px; font-family: var(--mono); font-size: 0.75rem; }
  :global(.status-pass) { color: var(--good); font-weight: 600; }
  :global(.status-fail) { color: var(--critical); font-weight: 600; }
  :global(.status-na), :global(.status-error) { color: var(--text-muted); }

  .top { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem 1.5rem; padding: 0.75rem 1.5rem; border-bottom: 1px solid var(--rule); background: var(--surface-1); }
  .brand { font-weight: 700; color: var(--text-primary); text-decoration: none; }
  nav { display: flex; gap: 1rem; flex-wrap: wrap; }
  nav a { color: var(--text-secondary); text-decoration: none; }
  nav a[aria-current='page'] { color: var(--text-primary); border-bottom: 2px solid var(--accent); }
  .runpick { margin-left: auto; display: flex; align-items: center; gap: 0.4rem; color: var(--text-secondary); font-size: 0.85rem; }
  .page { max-width: 1400px; margin: 0 auto; padding: 1rem 1.5rem 3rem; }
</style>
