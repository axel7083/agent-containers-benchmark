import { base } from '$app/paths';
import { seed } from '$lib/runs.svelte.js';

// Static SPA: data is fetched client-side from /data (published from the `data` branch).
export const prerender = true;
export const ssr = false;
// Emit `checks/index.html` rather than `checks.html` next to a `checks/` directory, which GitHub Pages cannot serve.
export const trailingSlash = 'always';

export async function load({ fetch }) {
  const get = async (path) => {
    const res = await fetch(`${base}/data/${path}`);
    if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
    return res.json();
  };
  const [index, catalog] = await Promise.all([
    get('index.json').catch(() => ({ runs: [] })),
    get('catalog.json').catch(() => null),
  ]);
  // Default to the newest of the largest completed runs, so a small smoke test does not hide the
  // full baseline; every run stays selectable.
  const runs = index.runs ?? [];
  const complete = runs.filter((r) => r.status === 'success');
  const largest = Math.max(0, ...complete.map((r) => r.n_planned ?? r.n_trials ?? 0));
  const latestFile = (complete.find((r) => (r.n_planned ?? r.n_trials ?? 0) === largest) ?? runs[0])?.file ?? '';
  let error = '';
  if (latestFile) {
    try {
      seed(latestFile, await get(latestFile));
    } catch (e) {
      error = String(e);
    }
  }
  return { index, catalog, error };
}
