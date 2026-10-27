import fs from 'node:fs';
import { runGate } from './gate.mjs';
import { createRegistryLookups, listCommentBodies } from './sources.mjs';

const {
  TRIVY_REPORT_PATH = '',
  HAS_LABEL = 'false',
  GITHUB_API_URL = '',
  GITHUB_REPOSITORY = '',
  PULL_REQUEST_NUMBER = '',
  GITHUB_TOKEN = '',
  GITHUB_STEP_SUMMARY = '',
} = process.env;

function appendSummary(text) {
  if (GITHUB_STEP_SUMMARY) {
    fs.appendFileSync(GITHUB_STEP_SUMMARY, text);
  }
}

try {
  const hasLabel = HAS_LABEL === 'true';
  const comments = hasLabel
    ? await listCommentBodies({
        apiUrl: GITHUB_API_URL,
        repository: GITHUB_REPOSITORY,
        pullRequestNumber: PULL_REQUEST_NUMBER,
        token: GITHUB_TOKEN,
      })
    : [];
  const result = await runGate({
    reportText: fs.existsSync(TRIVY_REPORT_PATH)
      ? fs.readFileSync(TRIVY_REPORT_PATH, 'utf8')
      : null,
    hasLabel,
    comments,
    lookups: createRegistryLookups(),
    now: Date.now(),
  });
  appendSummary(result.summary);
  for (const annotation of result.annotations) {
    console.log(annotation);
  }
  console.log(result.message);
  if (!result.passed) {
    console.log(`::error::${result.message}`);
    process.exitCode = 1;
  }
} catch (error) {
  appendSummary(`## Release gate\n\n${error.message}\n`);
  console.log(`::error::${error.message}`);
  process.exitCode = 1;
}
