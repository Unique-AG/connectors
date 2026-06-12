// Normalizes a raw MIME type for comparison: drops any '; param=value' suffix, trims, and
// lowercases. Returns '' for an empty input.
// e.g. 'IMAGE/PNG; charset=binary' -> 'image/png', '  text/HTML ' -> 'text/html'
export function normalizeMimeType(mimeType: string): string {
  return mimeType.split(';')[0]?.trim().toLowerCase() ?? '';
}

// Returns true when the given Confluence MIME type (e.g. 'image/png; charset=binary')
// denotes an image format. Strips any '; param=value' suffix and is case-insensitive.
export function isImageMimeType(mimeType: string): boolean {
  return normalizeMimeType(mimeType).startsWith('image/');
}
