const WATCHED_WORKFLOWS = ['[CI] Python', '[CI] Services', '[CI] Packages'];
export const FAILED_LABEL = 'deps-ci-failed';

export function failureLabelAction(runs, labels) {
  const latest = new Map();
  for (const { workflowName, conclusion } of runs) {
    if (WATCHED_WORKFLOWS.includes(workflowName) && !latest.has(workflowName)) {
      latest.set(workflowName, conclusion);
    }
  }
  const failed = [...latest.values()].includes('failure');
  const labeled = labels.includes(FAILED_LABEL);
  if (failed && !labeled) {
    return 'add';
  }
  return !failed && labeled ? 'remove' : 'none';
}
