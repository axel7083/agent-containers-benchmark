import { buildCatalog } from '$lib/catalog.server.js';

export function entries() {
  const catalog = buildCatalog();
  return Object.values(catalog?.families ?? {}).flatMap((f) => f.checks.map((c) => ({ id: c.id })));
}
