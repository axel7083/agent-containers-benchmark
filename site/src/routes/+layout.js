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
  const latestFile = index.runs?.[0]?.file ?? '';
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
