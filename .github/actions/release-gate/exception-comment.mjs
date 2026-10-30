export const MARKER = '<!-- release-gate-exception -->';

const MAX_HISTORY = 20;
const SHORT_SHA_LENGTH = 7;

function extractHistory(body) {
  return (body ?? '').split(/\r?\n/).filter((line) => line.startsWith('- '));
}

export function buildComment({ existingBody, action, actor, time, sha }) {
  const added = action === 'labeled';
  const entry = `- ${time}: ${actor} ${added ? 'added' : 'removed'} the label security-exception at commit ${sha.slice(0, SHORT_SHA_LENGTH)}`;
  const history = [...extractHistory(existingBody), entry].slice(-MAX_HISTORY);
  return [
    MARKER,
    '## Security exception on the release gate',
    '',
    `State: **${added ? 'ACTIVE' : 'REMOVED'}**`,
    '',
    `${added ? 'Set' : 'Removed'} by ${actor} at ${time}.`,
    '',
    'History:',
    '',
    ...history,
    '',
  ].join('\n');
}
