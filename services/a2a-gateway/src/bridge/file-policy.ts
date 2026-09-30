/**
 * Media types exchanged with external agents. Active content (HTML, SVG, scripts, executables) is
 * refused in both directions: remote output is data and is never rendered or executed.
 */
const ALLOWED_TYPES = [
  /^text\/(plain|markdown|csv|tab-separated-values)$/,
  /^application\/(pdf|json|xml|zip)$/,
  /^image\/(png|jpeg|gif|webp)$/,
  /^application\/vnd\.openxmlformats-officedocument\.(wordprocessingml\.document|spreadsheetml\.sheet|presentationml\.presentation)$/,
  /^application\/(msword|vnd\.ms-excel|vnd\.ms-powerpoint)$/,
];

export function isAllowedMediaType(mediaType: string): boolean {
  const normalized = mediaType.split(';')[0]?.trim().toLowerCase() ?? '';
  return ALLOWED_TYPES.some((pattern) => pattern.test(normalized));
}

export function normalizeMediaType(mediaType: string | undefined): string {
  return mediaType?.split(';')[0]?.trim().toLowerCase() || 'application/octet-stream';
}

/** A display-safe file name: no path, no control characters, bounded length. */
export function safeFilename(name: string | undefined, fallback: string): string {
  const base = (name ?? '').split(/[\\/]/).pop() ?? '';
  const cleaned = base
    .replace(/[\u0000-\u001f\u007f<>:"|?*]/g, '')
    .trim()
    .slice(0, 200);
  return cleaned || fallback;
}

/** Whether a peer that declared `modes` accepts `mediaType` (no modes means text only). */
export function acceptsMediaType(modes: string[], mediaType: string): boolean {
  const type = normalizeMediaType(mediaType);
  return modes.some(
    (mode) =>
      mode === '*/*' ||
      mode === type ||
      (mode.endsWith('/*') && type.startsWith(mode.slice(0, -1))),
  );
}
