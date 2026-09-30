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

/** Definitions of the benchmark as it is today (the Checks, Tasks and Methodology pages describe this). */
export function currentCatalog(run, current) {
  return current ?? run?.catalog;
}

/** A note when the selected run was graded with another dataset version than the one being described. */
export function versionNote(run, catalog) {
  const used = run?.dataset_version;
  const now = catalog?.dataset_version;
  return used != null && now != null && used !== now
    ? `These are the dataset v${now} definitions. The selected run used dataset v${used}, so tasks and checks added since then have no results in it.`
    : '';
}

/** Every check of the catalog in family order, each tagged with its family. */
export function allChecks(catalog) {
  // Ids key every list on the site: a catalog that repeats one (two families sharing an id) must not
  // crash the page, so the first definition wins.
  const seen = new Set();
  return Object.entries(catalog?.families ?? {})
    .flatMap(([family, f]) => f.checks.map((c) => ({ ...c, family })))
    .filter((c) => !seen.has(c.id) && seen.add(c.id));
}

/** Checks of the given families (all of them when omitted). */
export function checksOf(catalog, families) {
  const all = allChecks(catalog);
  if (!families) return all;
  const wanted = new Set([families].flat());
  return all.filter((c) => wanted.has(c.family));
}

export function gatesOf(catalog, kind = 'image') {
  return catalog?.gates_by_kind?.[kind] ?? catalog?.gates ?? [];
}
