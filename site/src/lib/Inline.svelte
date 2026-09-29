<script>
  /** Renders `code` spans from catalog text as <code>; everything else stays plain text (no HTML injection). */
  let { text = '' } = $props();
  let parts = $derived(String(text).split('`').map((value, i) => ({ value, code: i % 2 === 1 })));
</script>

{#each parts as p, i (i)}{#if p.code}<code>{p.value}</code>{:else}{p.value}{/if}{/each}
