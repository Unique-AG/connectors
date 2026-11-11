/** Collapses whitespace so a pasted multi-line subject cannot reflow an elicitation prompt. */
export function oneLine(value: string): string {
  return value.replaceAll(/\s+/g, ' ').trim();
}
