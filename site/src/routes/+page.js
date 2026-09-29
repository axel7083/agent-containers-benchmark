import { base } from '$app/paths';

/** Load the runs index and the latest run from the published `data` branch. */
export async function load({ fetch }) {
  const get = async (path) => {
    const res = await fetch(`${base}/data/${path}`);
    if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
    return res.json();
  };
  try {
    const index = await get('index.json');
    const latest = index.runs?.[0] ? await get(index.runs[0].file) : null;
    return { index, latest, error: '' };
  } catch (e) {
    return { index: null, latest: null, error: String(e) };
  }
}
