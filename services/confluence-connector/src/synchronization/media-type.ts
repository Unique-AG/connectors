// Returns true when the given Confluence media type (e.g. 'image/png; charset=binary')
// denotes an image format. Strips any '; param=value' suffix and is case-insensitive.
export function isImageMediaType(mediaType: string): boolean {
  const normalized = mediaType.split(';')[0]?.trim().toLowerCase() ?? '';
  return normalized.startsWith('image/');
}
