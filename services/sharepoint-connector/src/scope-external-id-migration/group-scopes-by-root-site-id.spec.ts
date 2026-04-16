import { describe, expect, it } from 'vitest';
import type { Scope } from '../unique-api/unique-scopes/unique-scopes.types';
import { groupScopesByRootSiteId } from './group-scopes-by-root-site-id';

function scope(id: string, parentId: string | null, externalId: string | null): Scope {
  return { id, name: `scope-${id}`, parentId, externalId };
}

const ROOT_SITE_A = 'site-a';
const ROOT_SITE_B = 'site-b';

describe('groupScopesByRootSiteId', () => {
  it('groups scopes under their root site', () => {
    const rootA = scope('r-a', null, `spc:site:${ROOT_SITE_A}`);
    const driveA = scope('d-a', 'r-a', `spc:drive:${ROOT_SITE_A}/drive-1`);
    const folderA = scope('f-a', 'd-a', `spc:folder:${ROOT_SITE_A}/item-1`);

    const rootB = scope('r-b', null, `spc:site:${ROOT_SITE_B}`);
    const driveB = scope('d-b', 'r-b', `spc:drive:${ROOT_SITE_B}/drive-2`);

    const groups = groupScopesByRootSiteId([rootA, driveA, folderA, rootB, driveB]);

    expect(groups.get(ROOT_SITE_A)).toEqual([rootA, driveA, folderA]);
    expect(groups.get(ROOT_SITE_B)).toEqual([rootB, driveB]);
  });

  it('excludes scopes whose parent chain does not reach a root scope', () => {
    const rootA = scope('r-a', null, `spc:site:${ROOT_SITE_A}`);
    const orphan = scope('orphan', 'nonexistent-parent', 'spc:drive:unknown-site/drive-x');

    const groups = groupScopesByRootSiteId([rootA, orphan]);

    expect(groups.get(ROOT_SITE_A)).toEqual([rootA]);
    expect([...groups.values()].flat()).not.toContainEqual(orphan);
  });

  it('returns empty map for empty input', () => {
    expect(groupScopesByRootSiteId([]).size).toBe(0);
  });

  it('handles deeply nested parentId chains', () => {
    const root = scope('r', null, 'spc:site:deep-site');
    const child1 = scope('c1', 'r', null);
    const child2 = scope('c2', 'c1', null);
    const child3 = scope('c3', 'c2', null);

    const groups = groupScopesByRootSiteId([root, child1, child2, child3]);
    expect(groups.get('deep-site')).toEqual([root, child1, child2, child3]);
  });

  it('resolves all children when they are input in arbitrary order', () => {
    const root = scope('r', null, 'spc:site:ordered-site');
    const child = scope('c', 'r', null);
    const grandchild = scope('gc', 'c', null);

    const groups = groupScopesByRootSiteId([grandchild, child, root]);
    expect(groups.get('ordered-site')).toEqual(expect.arrayContaining([root, child, grandchild]));
    expect(groups.get('ordered-site')).toHaveLength(3);
  });

  it('ignores scopes with new-format externalIds as root markers', () => {
    // A scope with a new-format externalId is not a legacy root; it must not
    // be treated as a grouping anchor.
    const newFormatRoot = scope('nf', null, 'spc:nf-site/site');
    const child = scope('c', 'nf', null);

    const groups = groupScopesByRootSiteId([newFormatRoot, child]);
    expect(groups.size).toBe(0);
  });

  it('groups multiple disjoint trees independently', () => {
    const rootA = scope('r-a', null, `spc:site:${ROOT_SITE_A}`);
    const childA = scope('c-a', 'r-a', null);
    const rootB = scope('r-b', null, `spc:site:${ROOT_SITE_B}`);
    const childB = scope('c-b', 'r-b', null);

    const groups = groupScopesByRootSiteId([rootA, childA, rootB, childB]);
    expect(groups.size).toBe(2);
    expect(groups.get(ROOT_SITE_A)).toEqual([rootA, childA]);
    expect(groups.get(ROOT_SITE_B)).toEqual([rootB, childB]);
  });

  it('attributes sibling subtrees sharing a parent to the same root', () => {
    const root = scope('r', null, 'spc:site:memo-site');
    const child1 = scope('c1', 'r', null);
    const child2 = scope('c2', 'r', null);
    const grandchild = scope('gc', 'c1', null);

    const groups = groupScopesByRootSiteId([root, child1, child2, grandchild]);
    expect(groups.get('memo-site')).toEqual([root, child1, child2, grandchild]);
  });
});
