<script>
  let { children } = $props();
</script>

<div class="page">
  {@render children()}
</div>

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
  .page { max-width: 1400px; margin: 0 auto; padding: 1.5rem; }
</style>
