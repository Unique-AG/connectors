const DEPS = 'deps';
const FALLBACK = 'main';

function globToRegExp(glob) {
  const source = glob
    .replace(/[.+?^${}()|[\]\\]/g, '\\$&')
    .replace(/\*\*\//g, '<ANY_DIRECTORIES>')
    .replace(/\*\*/g, '<ANY_PATH>')
    .replace(/\*/g, '[^/]*')
    .replaceAll('<ANY_DIRECTORIES>', '(?:.*/)?')
    .replaceAll('<ANY_PATH>', '.*');
  return new RegExp(`^${source}$`);
}

function parseScopes(gitcommitizen) {
  const section = gitcommitizen.split(/^\[scopes\]$/m)[1]?.split(/^\[/m)[0] ?? '';
  return section
    .split('\n')
    .map((line) => /^([\w-]+) = (.+)$/.exec(line.trim()))
    .filter(Boolean)
    .map(([, name, globs]) => ({
      name,
      patterns: globs.split(',').map((glob) => globToRegExp(glob.trim())),
    }))
    .filter(({ name }) => name !== FALLBACK);
}

export function commitScope(files, gitcommitizen) {
  const scopes = parseScopes(gitcommitizen);
  const perFile = files.map((file) =>
    scopes
      .filter(({ patterns }) => patterns.some((pattern) => pattern.test(file)))
      .map(({ name }) => name),
  );
  const common = (perFile[0] ?? []).filter((name) => perFile.every((names) => names.includes(name)));
  return common.includes(DEPS) ? DEPS : (common[0] ?? FALLBACK);
}
