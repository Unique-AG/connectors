import assert from 'node:assert';
import { describe, it } from 'node:test';
import { FAILED_LABEL, failureLabelAction, READY_LABEL, reviewLabelAction } from './ci-label.mjs';

const run = (workflowName, conclusion, status = 'completed') => ({
  workflowName,
  conclusion,
  status,
});

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

describe('reviewLabelAction', () => {
  const green = [run('[CI] Python', 'success'), run('[CI] Services', 'success')];

  it('adds the label when every watched workflow passed', () => {
    assert.strictEqual(reviewLabelAction(green, ['dependencies']), 'add');
  });

  it('waits while a watched workflow still runs', () => {
    const runs = [run('[CI] Python', 'success'), run('[CI] Services', '', 'in_progress')];
    assert.strictEqual(reviewLabelAction(runs, []), 'none');
  });

  it('adds nothing when a watched workflow failed', () => {
    assert.strictEqual(reviewLabelAction([run('[CI] Python', 'failure')], []), 'none');
  });

  it('adds nothing when no watched workflow ran', () => {
    assert.strictEqual(reviewLabelAction([run('[CI] Helm', 'success')], []), 'none');
  });

  it('adds nothing after the review is done or a person has the update', () => {
    assert.strictEqual(reviewLabelAction(green, ['deps-reviewed']), 'none');
    assert.strictEqual(reviewLabelAction(green, ['deps-needs-human']), 'none');
  });

  it('does nothing when the label is already there', () => {
    assert.strictEqual(reviewLabelAction(green, [READY_LABEL]), 'none');
  });

  it('removes the label when the CI is not green any more', () => {
    assert.strictEqual(reviewLabelAction([run('[CI] Python', 'failure')], [READY_LABEL]), 'remove');
  });
});
