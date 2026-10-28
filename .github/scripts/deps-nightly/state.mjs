import { createHash } from 'node:crypto';

const MARKER = /<!-- deps-nightly:(\S+) -->/;
const HANDLED_LABELS = ['ai-assisted', 'human-required'];

export function entryKey({ slug, members }) {
  const targets = members
    .map(({ name, to }) => `${name}@${to}`)
    .sort()
    .join('\n');
  return `${slug}:${createHash('sha256').update(targets).digest('hex').slice(0, 12)}`;
}

export const markerOf = (key) => `<!-- deps-nightly:${key} -->`;

export const markerKeyOf = (body) => MARKER.exec(body ?? '')?.[1] ?? null;

export const closedKeysOf = (bodies) => new Set(bodies.map(markerKeyOf).filter(Boolean));

export function classifyOpenPull({ key, pull }) {
  if (markerKeyOf(pull.body) !== key) {
    return 'replace';
  }
  if (pull.behindBy === 0) {
    return 'keep';
  }
  const handled = pull.humanCommits || pull.labels.some((label) => HANDLED_LABELS.includes(label));
  return handled ? 'update' : 'rebuild';
}
