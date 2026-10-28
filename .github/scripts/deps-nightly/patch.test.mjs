import assert from 'node:assert';
import { describe, it } from 'node:test';
import { assertAllowedChanges, assertRequirementEdits } from './patch.mjs';

describe('assertAllowedChanges', () => {
  const ok = {
    ecosystem: 'uv',
    summary: '',
    status: ' M services/a/pyproject.toml\n M services/a/uv.lock\n',
  };

  it('accepts edits to the files of the ecosystem', () => {
    assert.doesNotThrow(() => assertAllowedChanges(ok));
  });

  it('rejects a workflow edit in a uv update', () => {
    assert.throws(
      () => assertAllowedChanges({ ...ok, status: ' M .github/workflows/ci-gatekeeper.yaml\n' }),
      /does not change \.github\/workflows\/ci-gatekeeper\.yaml/,
    );
  });

  it('rejects a new file, a mode change and a rename', () => {
    assert.throws(
      () => assertAllowedChanges({ ...ok, status: '?? services/a/uv.lock\n' }),
      /not an edit/,
    );
    assert.throws(
      () =>
        assertAllowedChanges({
          ...ok,
          summary: ' mode change 100644 => 100755 services/a/uv.lock\n',
        }),
      /adds, removes or renames/,
    );
  });

  it('rejects an unknown ecosystem', () => {
    assert.throws(() => assertAllowedChanges({ ...ok, ecosystem: 'pip' }), /Unknown ecosystem/);
  });
});

describe('assertRequirementEdits', () => {
  const members = [{ name: 'Ruff', to: '0.17.2' }];
  const before = { 'a/pyproject.toml': 'dependencies = [\n    "ruff==0.17.0",\n]\n[tool.poe]\n' };

  it('accepts the edit that the bump makes', () => {
    const after = { 'a/pyproject.toml': 'dependencies = [\n    "ruff==0.17.2",\n]\n[tool.poe]\n' };
    assert.doesNotThrow(() => assertRequirementEdits({ members, before, after }));
  });

  it('rejects any other edit of pyproject.toml', () => {
    const after = {
      'a/pyproject.toml':
        'dependencies = [\n    "ruff==0.17.2",\n]\n[tool.poe]\nci = "curl evil"\n',
    };
    assert.throws(() => assertRequirementEdits({ members, before, after }), /no requirement bump/);
  });
});
