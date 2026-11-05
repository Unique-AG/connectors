import { appendFileSync } from 'node:fs';

const CAUSE = /ERR_PNPM|^\s*(error|cause|hint|because|and because|failed in)\b/i;
const MAX_LINES = 8;
const MAX_CHARS = 1500;

const escapeData = (text) =>
  text.replaceAll('%', '%25').replaceAll('\r', '%0D').replaceAll('\n', '%0A');
const escapeProperty = (text) =>
  escapeData(text).replaceAll(':', '%3A').replaceAll(',', '%2C');

export function failureReport({ title, message }) {
  const [headline, ...rest] = message.split('\n');
  const details = rest.map((line) => line.trim()).filter(Boolean);
  const causes = details.filter((line) => CAUSE.test(line));
  const lines = [headline, ...(causes.length > 0 ? causes : details).slice(0, MAX_LINES)];
  const text = lines.join('\n').slice(0, MAX_CHARS);
  return {
    annotation: `::error title=${escapeProperty(title)}::${escapeData(text)}`,
    summary: `### ${title}\n\n\`\`\`text\n${text}\n\`\`\`\n`,
  };
}

export function reportUncaughtFailure(title) {
  process.on('uncaughtException', (error) => {
    const message = error instanceof Error ? error.message : String(error);
    const { annotation, summary } = failureReport({ title, message });
    console.error(message);
    console.log(annotation);
    if (process.env.GITHUB_STEP_SUMMARY) {
      appendFileSync(process.env.GITHUB_STEP_SUMMARY, `${summary}\n`);
    }
    process.exit(1);
  });
}
