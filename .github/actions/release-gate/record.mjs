import { buildComment, MARKER } from './exception-comment.mjs';
import { upsertComment } from './sources.mjs';

const {
  ACTION = '',
  ACTOR = '',
  HEAD_SHA = '',
  GITHUB_API_URL = '',
  GITHUB_REPOSITORY = '',
  PULL_REQUEST_NUMBER = '',
  GITHUB_TOKEN = '',
} = process.env;

try {
  const time = new Date().toISOString();
  await upsertComment({
    apiUrl: GITHUB_API_URL,
    repository: GITHUB_REPOSITORY,
    pullRequestNumber: PULL_REQUEST_NUMBER,
    token: GITHUB_TOKEN,
    marker: MARKER,
    build: (existingBody) =>
      buildComment({ existingBody, action: ACTION, actor: ACTOR, time, sha: HEAD_SHA }),
  });
  console.log(`Recorded that ${ACTOR} ${ACTION} the label security-exception.`);
} catch (error) {
  console.log(`::error::${error.message}`);
  process.exitCode = 1;
}
