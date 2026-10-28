const REGISTRY_URL = 'https://registry.npmjs.org';
const TIMEOUT_MS = 20_000;
const CONCURRENCY = 8;
const MAX_MESSAGE_LENGTH = 120;

export function createNpmDeprecationLookup(fetchImpl = fetch) {
  return {
    async deprecated(name, version) {
      try {
        const response = await fetchImpl(`${REGISTRY_URL}/${name.replace('/', '%2F')}/${version}`, {
          signal: AbortSignal.timeout(TIMEOUT_MS),
        });
        if (response.status !== 200) {
          return null;
        }
        const { deprecated } = await response.json();
        return typeof deprecated === 'string' && deprecated ? deprecated : null;
      } catch {
        return null;
      }
    },
  };
}

async function mapWithLimit(items, limit, task) {
  const results = new Array(items.length);
  let next = 0;
  const worker = async () => {
    while (next < items.length) {
      const index = next++;
      results[index] = await task(items[index]);
    }
  };
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker));
  return results;
}

async function deprecationReason({ ecosystem, name, to }, lookup) {
  if (ecosystem !== 'npm') {
    return null;
  }
  for (const version of to.split(',').map((part) => part.trim())) {
    const message = version && (await lookup.deprecated(name, version));
    if (message) {
      return `The version ${version} is deprecated: ${message.slice(0, MAX_MESSAGE_LENGTH)}`;
    }
  }
  return null;
}

export async function dropDeprecated({ candidates, lookup }) {
  const reasons = await mapWithLimit(candidates, CONCURRENCY, (candidate) =>
    deprecationReason(candidate, lookup),
  );
  return {
    candidates: candidates.filter((_, index) => reasons[index] === null),
    needsPerson: candidates.flatMap(({ name }, index) =>
      reasons[index] === null ? [] : [{ ecosystem: 'npm', name, reason: reasons[index] }],
    ),
  };
}
