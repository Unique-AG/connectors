export function normalizeMediaType(mediaType: string): string {
  return mediaType.split(';')[0]?.trim().toLowerCase() ?? '';
}

// Returns true when the given Confluence media type (e.g. 'image/png; charset=binary')
// denotes an image format. Strips any '; param=value' suffix and is case-insensitive.
export function isImageMediaType(mediaType: string): boolean {
  return normalizeMediaType(mediaType).startsWith('image/');
}
