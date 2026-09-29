import { base } from '$app/paths';

/** Run shared by every page; the layout seeds it with the latest published run. */
export const view = $state({ file: '', run: null, error: '' });

const cache = new Map();

export async function selectRun(file) {
  view.file = file;
  view.error = '';
  try {
    if (!cache.has(file)) {
      const res = await fetch(`${base}/data/${file}`);
      if (!res.ok) throw new Error(`${file}: HTTP ${res.status}`);
      cache.set(file, await res.json());
    }
    view.run = cache.get(file);
  } catch (e) {
    view.error = String(e);
  }
}

export function seed(file, run) {
  if (view.file || !file) return;
  view.file = file;
  view.run = run;
  cache.set(file, run);
}

/** Definitions a run was graded with; falls back to the current catalog for older runs. */
export function catalogOf(run, current) {
  return run?.catalog ?? current;
}

export function checksOf(catalog, family = 'containerfile') {
  return catalog?.families?.[family]?.checks ?? [];
}
