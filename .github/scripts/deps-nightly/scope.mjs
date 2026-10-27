const DEPS = 'deps';
const FALLBACK = 'main';

function globToRegExp(glob) {
  return new RegExp(`^${glob.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/\*+/g, '.*')}$`);
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
  const matchesOf = (file) =>
    scopes
      .filter(({ patterns }) => patterns.some((pattern) => pattern.test(file)))
      .map(({ name }) => name);
  const perFile = files.map(matchesOf);
  if (perFile.length === 0 || perFile.some((names) => names.length === 0)) {
    return FALLBACK;
  }
  if (perFile.every((names) => names.includes(DEPS))) {
    return DEPS;
  }
  const single = perFile.map((names) => (names.length === 1 ? names[0] : undefined));
  return single[0] && single.every((name) => name === single[0]) ? single[0] : FALLBACK;
}
