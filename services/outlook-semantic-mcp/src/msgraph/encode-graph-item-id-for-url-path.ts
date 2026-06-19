export function encodeGraphItemIdForUrlPath(id: string): string {
  return id.replaceAll('/', '-');
}
