export const normalizeSlashes = (value: string): string => {
  // 1. Remove leading/trailing whitespace
  let result = value.trim();

  // 2. Remove leading and trailing slashes
  result = result.replace(/^\/+|\/+$/g, '');

  // 3. Replace multiple consecutive slashes with single slash
  result = result.replace(/\/+/g, '/');

  return result;
};

// Returns true if `path` is an ancestor of `rootPath` (i.e., if `rootPath` starts with `{path}/`
// and they're not equal). `path` and `rootPath` are expected to have normalized slashes.
// The root path `/` is treated as an ancestor of any root path (except when root path itself is `/`).
// Examples:
//   isAncestorOfRootPath('/Top', '/Top/Middle/IngestionRoot')           // true
//   isAncestorOfRootPath('/Top/Middle', '/Top/Middle/IngestionRoot')    // true
//   isAncestorOfRootPath('/Top/Middle/IngestionRoot', '/Top/Middle/IngestionRoot') // false
//   isAncestorOfRootPath('/Top/Middle/IngestionRoot/Folder', '/Top/Middle/IngestionRoot') // false
//   isAncestorOfRootPath('/', '/Root')                                   // true
//   isAncestorOfRootPath('/', '/')                                       // false
export function isAncestorOfRootPath(path: string, rootPath: string): boolean {
  if (path === rootPath) {
    return false;
  }
  // Root path '/' is an ancestor of any root path (except when root path itself is '/')
  if (path === '/') {
    return true;
  }
  // Check if the normalized root path starts with this path followed by a slash
  return rootPath.startsWith(`${path}/`);
}
