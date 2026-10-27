import assert from 'node:assert';
import { describe, it } from 'node:test';
import { FAILED_LABEL, failureLabelAction } from './ci-label.mjs';

const run = (workflowName, conclusion) => ({ workflowName, conclusion });

describe('failureLabelAction', () => {
  it('adds the label when a watched workflow failed', () => {
    assert.strictEqual(failureLabelAction([run('[CI] Python', 'failure')], []), 'add');
  });

  it('does nothing when the label is already there', () => {
    assert.strictEqual(failureLabelAction([run('[CI] Python', 'failure')], [FAILED_LABEL]), 'none');
  });

  it('removes the label when the watched workflows pass', () => {
    const runs = [run('[CI] Python', 'success'), run('[CI] Services', 'success')];
    assert.strictEqual(failureLabelAction(runs, [FAILED_LABEL, 'dependencies']), 'remove');
  });

  it('keeps the label while another watched workflow still fails', () => {
    const runs = [run('[CI] Python', 'success'), run('[CI] Services', 'failure')];
    assert.strictEqual(failureLabelAction(runs, [FAILED_LABEL]), 'none');
  });

  it('reads only the newest run of each workflow', () => {
    const runs = [run('[CI] Python', 'success'), run('[CI] Python', 'failure')];
    assert.strictEqual(failureLabelAction(runs, [FAILED_LABEL]), 'remove');
  });

  it('ignores workflows that are not watched', () => {
    assert.strictEqual(failureLabelAction([run('[CI] Helm', 'failure')], []), 'none');
  });
});
