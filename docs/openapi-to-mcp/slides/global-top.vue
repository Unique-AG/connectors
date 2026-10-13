<template>
  <div v-if="$slidev.nav.currentPage > 1" class="deck-footer">
    <span><b>Unique AI</b> · From an OpenAPI spec to an MCP server</span>
    <span>SM · 13 Oct 2026 · {{ $slidev.nav.currentPage }} / {{ $slidev.nav.total }}</span>
  </div>
</template>
