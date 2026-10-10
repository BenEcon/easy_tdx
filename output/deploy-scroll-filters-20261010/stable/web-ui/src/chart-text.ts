/** Chart tooltips are HTML strings, including when their text comes from an imported archive. */
export function escapeChartText(value: unknown): string {
  return String(value ?? '').replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]!))
}
