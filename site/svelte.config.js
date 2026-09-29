import adapter from '@sveltejs/adapter-static';

/** @type {import('@sveltejs/kit').Config} */
export default {
  kit: {
    adapter: adapter({ pages: 'build', assets: 'build', fallback: undefined, strict: true }),
    paths: { base: process.env.BASE_PATH ?? '' },
    // /checks/[id] and /tasks/[id] are enumerated from data/catalog.json; without it (local build
    // with no data) there is nothing to prerender for them, which is not an error.
    prerender: { handleUnseenRoutes: 'warn' },
  },
};
