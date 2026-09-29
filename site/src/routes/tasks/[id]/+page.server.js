import { buildCatalog } from '$lib/catalog.server.js';

export function entries() {
  return (buildCatalog()?.tasks ?? []).map((t) => ({ id: t.id }));
}
