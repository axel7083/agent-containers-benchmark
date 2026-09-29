import { readFileSync } from 'node:fs';

/** Catalog generated into static/data by CI; used at build time to prerender one page per check and task. */
export function buildCatalog() {
  try {
    return JSON.parse(readFileSync('static/data/catalog.json', 'utf8'));
  } catch {
    return null;
  }
}
