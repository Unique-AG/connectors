import assert from 'node:assert';
import { describe, it } from 'node:test';
import { failureReport } from './annotate.mjs';

const title = 'Bump uv-tiktoken failed';

describe('failureReport', () => {
  it('keeps the cause lines of a uv resolver error and drops the progress lines', () => {
    const message = [
      'uv lock --exclude-newer 3 days --upgrade-package tiktoken==0.14.0 failed:',
      'Using CPython 3.14.6',
      'Resolving despite existing lockfile due to addition of global exclude newer 2026-10-31',
      "error: No solution found when resolving dependencies for split (markers: python_full_version >= '3.15')",
      '  cause: Because unique-sdk==2026.44.2 depends on tiktoken>=0.12.0,<0.13 and tiktoken==0.14.0, we can conclude that unique-sdk==2026.44.2 cannot be used.',
      '         And because your project depends on unique-sdk==2026.44.2, we can conclude that your project\'s requirements are unsatisfiable.',
      '',
      'hint: While the active Python version is 3.14, the resolution failed for other Python versions.',
    ].join('\n');
    const { annotation } = failureReport({ title, message });
    assert.ok(annotation.startsWith('::error title=Bump uv-tiktoken failed::'));
    assert.ok(annotation.includes('failed:%0Aerror: No solution found'));
    assert.ok(annotation.includes('cause: Because unique-sdk==2026.44.2 depends on tiktoken'));
    assert.ok(annotation.includes('And because your project depends on unique-sdk'));
    assert.ok(!annotation.includes('Using CPython'));
  });

  it('keeps the error and the project of a failed lock check among the progress lines', () => {
    const message = [
      'bash scripts/each-python-project.sh uv lock --check failed:',
      '== packages/mcp-architecture: uv lock --check',
      'Resolved 76 packages in 4ms',
      'error: The lockfile at `uv.lock` needs to be updated, but `--check` was provided.',
      'hint: To update the lockfile, run `uv lock`.',
      'Resolved 165 packages in 5ms',
      'Failed in: packages/mcp-scaffold',
    ].join('\n');
    const { annotation } = failureReport({ title, message });
    assert.ok(annotation.includes('needs to be updated'));
    assert.ok(annotation.includes('Failed in: packages/mcp-scaffold'));
    assert.ok(!annotation.includes('Resolved 76 packages'));
  });

  it('keeps the first lines of a message without a cause line', () => {
    const message = [
      'The bump does not match the entry. Put packages that must move together in one group in .github/deps-groups.json.',
      '@babel/types 7.29.11 -> 7.29.12',
    ].join('\n');
    const { annotation } = failureReport({ title: 'Bump npm-babel-parser failed', message });
    assert.ok(annotation.includes('one group in .github/deps-groups.json.%0A@babel/types'));
  });

  it('escapes the characters that end a workflow command', () => {
    const { annotation } = failureReport({ title: 'a: b, c', message: '100% sure\nrest' });
    assert.ok(annotation.startsWith('::error title=a%3A b%2C c::100%25 sure%0Arest'));
  });

  it('writes the same lines into the job summary', () => {
    const { summary } = failureReport({ title, message: 'cz rejects the title\nerror: scope' });
    assert.strictEqual(summary, `### ${title}\n\n\`\`\`text\ncz rejects the title\nerror: scope\n\`\`\`\n`);
  });

  it('limits the length of the text', () => {
    const { annotation } = failureReport({ title, message: `x\n${'error: y'.repeat(1000)}` });
    assert.ok(annotation.length < 1700);
  });
});
