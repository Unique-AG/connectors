import { compareVersions } from './versions.mjs';

const DAY_MS = 24 * 60 * 60 * 1000;
const HUB_URL = 'https://hub.docker.com/v2/repositories/library';
const AUTH_URL = 'https://auth.docker.io/token?service=registry.docker.io&scope=repository:library';
const REGISTRY_URL = 'https://registry-1.docker.io/v2/library';
const INDEX_ACCEPT =
  'application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json';
const MAX_PAGES = 10;
const TIMEOUT_MS = 20_000;
const PIN_LINE =
  /^(FROM\s+(?:--platform=\S+\s+)?|COPY\s+(?:--\S+\s+)*--from=)(\S+?):([^\s:@/]+)@(sha256:[0-9a-f]{64})([^\n]*)$/i;
const PATCH_TAG = /^(\d+)\.(\d+)\.(\d+)(-.+)?$/;

const refOf = ({ image, tag, digest }) => `${image}:${tag}@${digest}`;
const shortRef = (tag, digest) => `${tag}@${digest.slice('sha256:'.length, 'sha256:'.length + 12)}`;

function parseFromLine(line) {
  const match = PIN_LINE.exec(line);
  return match
    ? { prefix: match[1], image: match[2], tag: match[3], digest: match[4], rest: match[5] }
    : undefined;
}

export function parseFromLines(text) {
  return text.split('\n').flatMap((line) => {
    const parsed = parseFromLine(line);
    return parsed ? [{ image: parsed.image, tag: parsed.tag, digest: parsed.digest }] : [];
  });
}

function findTarget(current, tags, cutoff) {
  const eligible = tags.filter((tag) => Date.parse(tag.pushedAt) <= cutoff);
  const pinned = PATCH_TAG.exec(current.tag);
  if (!pinned) {
    return eligible.find((tag) => tag.name === current.tag);
  }
  const [, major, minor, patch, suffix = ''] = pinned;
  const sameTrain = eligible.flatMap((tag) => {
    const match = PATCH_TAG.exec(tag.name);
    return match && match[1] === major && (match[4] ?? '') === suffix
      ? [{ tag, version: `${match[1]}.${match[2]}.${match[3]}` }]
      : [];
  });
  const newest = sameTrain.reduce(
    (best, entry) => (!best || compareVersions(entry.version, best.version) > 0 ? entry : best),
    undefined,
  );
  return newest && compareVersions(newest.version, `${major}.${minor}.${patch}`) >= 0
    ? newest.tag
    : undefined;
}

async function isNoOpRefresh(image, current, target, lookup) {
  if (target.name !== current.tag || !target.platforms?.length) {
    return false;
  }
  const previous = await lookup.platforms(image, current.digest).catch(() => []);
  return previous.join() === target.platforms.join();
}

async function planImage(image, used, lookup, cutoff) {
  const failure = (reason) => ({
    candidates: [],
    needsPerson: [{ ecosystem: 'docker', name: image, reason }],
  });
  if (image.includes('/')) {
    return failure('Only Docker Hub official images are updated.');
  }
  let tags;
  try {
    tags = await lookup.tags(image);
  } catch {
    return failure('The tag lookup failed.');
  }
  const planned = await Promise.all(
    used.map(async (current) => {
      const target = findTarget(current, tags, cutoff);
      if (
        !target ||
        (target.name === current.tag && target.digest === current.digest) ||
        (await isNoOpRefresh(image, current, target, lookup))
      ) {
        return [];
      }
      return [
        {
          ecosystem: 'docker',
          name: image,
          from: shortRef(current.tag, current.digest),
          to: shortRef(target.name, target.digest),
          direct: true,
          data: {
            fromRef: `${current.tag}@${current.digest}`,
            toRef: `${target.name}@${target.digest}`,
          },
        },
      ];
    }),
  );
  const candidates = planned.flat();
  return { candidates, needsPerson: [] };
}

export async function planDocker({ files, lookup, now, cooldownDays }) {
  const cutoff = now - cooldownDays * DAY_MS;
  const distinct = new Map(
    Object.values(files)
      .flatMap(parseFromLines)
      .map((used) => [refOf(used), used]),
  );
  const byImage = Map.groupBy(distinct.values(), ({ image }) => image);
  const plans = await Promise.all(
    [...byImage].map(([image, used]) => planImage(image, used, lookup, cutoff)),
  );
  return {
    candidates: plans.flatMap(({ candidates }) => candidates),
    needsPerson: plans.flatMap(({ needsPerson }) => needsPerson),
  };
}

function applyToText(text, name, { fromRef, toRef }) {
  const from = `${name}:${fromRef}`;
  return text
    .split('\n')
    .map((line) => {
      const parsed = parseFromLine(line);
      return parsed && refOf(parsed) === from
        ? `${parsed.prefix}${name}:${toRef}${parsed.rest}`
        : line;
    })
    .join('\n');
}

export function applyDocker(files, { name, data }) {
  return Object.fromEntries(
    Object.entries(files)
      .map(([path, text]) => [path, applyToText(text, name, data)])
      .filter(([path, text]) => text !== files[path]),
  );
}

async function getJson(fetchImpl, url, headers) {
  const response = await fetchImpl(url, { headers, signal: AbortSignal.timeout(TIMEOUT_MS) });
  if (response.status === 429 || response.status >= 500) {
    throw new Error(`The registry answered ${response.status} for ${url}.`);
  }
  return response.status === 200 ? response.json() : undefined;
}

export function createDockerLookup(fetchImpl = fetch) {
  return {
    async tags(image) {
      const found = [];
      let url = `${HUB_URL}/${encodeURIComponent(image)}/tags?page_size=100&ordering=last_updated`;
      for (let page = 0; url && page < MAX_PAGES; page++) {
        const body = await getJson(fetchImpl, url);
        if (!body) {
          return [];
        }
        for (const tag of body.results ?? []) {
          const digest = tag.digest ?? tag.images?.[0]?.digest;
          if (digest) {
            found.push({
              name: tag.name,
              digest,
              pushedAt: tag.tag_last_pushed ?? tag.last_updated,
              platforms: (tag.images ?? [])
                .filter((entry) => entry.digest && entry.architecture !== 'unknown')
                .map((entry) => entry.digest)
                .sort(),
            });
          }
        }
        url = body.next;
      }
      return found;
    },
    async platforms(image, digest) {
      const { token } = await getJson(fetchImpl, `${AUTH_URL}/${image}:pull`);
      const index = await getJson(fetchImpl, `${REGISTRY_URL}/${image}/manifests/${digest}`, {
        Accept: INDEX_ACCEPT,
        Authorization: `Bearer ${token}`,
      });
      return (index?.manifests ?? [])
        .filter(({ platform }) => platform?.architecture !== 'unknown')
        .map((manifest) => manifest.digest)
        .sort();
    },
  };
}
