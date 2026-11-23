const REGISTRY_URL = 'https://registry.npmjs.org';
const TIMEOUT_MS = 20_000;
const ATTEMPTS = 2;
const CONCURRENCY = 8;
const MAX_MESSAGE_LENGTH = 120;

export function createNpmDeprecationLookup(fetchImpl = fetch) {
  return {
    async deprecated(name, version) {
      for (let attempt = 0; attempt < ATTEMPTS; attempt++) {
        try {
          const response = await fetchImpl(
            `${REGISTRY_URL}/${name.replaceAll('/', '%2F')}/${version}`,
            {
              signal: AbortSignal.timeout(TIMEOUT_MS),
            },
          );
          if (response.status === 404) {
            return null;
          }
          if (response.status === 200) {
            const { deprecated } = await response.json();
            return typeof deprecated === 'string' && deprecated ? deprecated : null;
          }
        } catch {}
      }
      return undefined;
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
  let unanswered = null;
  for (const version of to
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean)) {
    const message = await lookup.deprecated(name, version);
    if (message) {
      return `The version ${version} is deprecated: ${message.slice(0, MAX_MESSAGE_LENGTH)}`;
    }
    if (message === undefined && unanswered === null) {
      unanswered = `The npm registry did not answer for ${version}. The job cannot check whether it is deprecated.`;
    }
  }
  return unanswered;
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
