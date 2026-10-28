import assert from 'node:assert';
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { runOrThrow, sandboxEnv } from './run.mjs';
import { compareVersions } from './versions.mjs';

export const LOCK_FILE = '.terraform.lock.hcl';
const BLOCK = /^provider "([^"]+)" \{\n[\s\S]*?^\}\n/gm;

export const providerAddress = (source) =>
  source.split('/').length === 2 ? `registry.terraform.io/${source}` : source;

const blocksOf = (text) =>
  [...text.matchAll(BLOCK)].map((match) => ({ address: match[1], text: match[0] }));

export function parseLock(text) {
  return new Map(
    blocksOf(text ?? '').map(({ address, text: block }) => [
      address,
      /^\s*version\s*=\s*"([^"]+)"/m.exec(block)?.[1],
    ]),
  );
}

const OPERATOR_ORDER = ['>', '>=', '~>', '!=', '<=', '<'];
const PART = /^\s*(~>|>=|<=|!=|>|<|=)?\s*(\d+(?:\.\d+)*)\s*$/;

export function normalizeConstraint(constraint) {
  return constraint
    .split(',')
    .map((part) => {
      const match = PART.exec(part);
      assert.ok(match, `Not a version constraint: ${part}`);
      const [, operator = '=', version] = match;
      const numbers = version.split('.');
      const width = operator === '~>' ? Math.max(2, numbers.length) : 3;
      return {
        operator,
        version,
        text: [...numbers, '0', '0'].slice(0, Math.max(width, numbers.length)).join('.'),
      };
    })
    .sort(
      (a, b) =>
        OPERATOR_ORDER.indexOf(a.operator) - OPERATOR_ORDER.indexOf(b.operator) ||
        compareVersions(a.version, b.version),
    )
    .map(({ operator, text }) => (operator === '=' ? text : `${operator} ${text}`))
    .join(', ');
}

export function mergeLockBlock(existing, generated, constraint) {
  const [fresh] = blocksOf(generated);
  assert.ok(fresh, 'Terraform wrote no provider block.');
  const block = fresh.text.replace(
    /^(\s*constraints\s*=\s*")[^"]*(")/m,
    (_, before, after) => `${before}${normalizeConstraint(constraint)}${after}`,
  );
  const header = (existing ?? generated).split(/^provider /m)[0];
  return (
    header +
    [
      ...blocksOf(existing ?? '').filter(({ address }) => address !== fresh.address),
      { address: fresh.address, text: block },
    ]
      .sort((a, b) => a.address.localeCompare(b.address))
      .map(({ text: kept }) => kept)
      .join('\n')
  );
}

const runTerraform = (args, cwd) => runOrThrow('terraform', args, { cwd, env: sandboxEnv() });

export function generateLock({ source, version, platforms, terraform = runTerraform }) {
  const directory = mkdtempSync(join(tmpdir(), 'terraform-lock-'));
  writeFileSync(
    join(directory, 'versions.tf'),
    `terraform {\n  required_providers {\n    pinned = {\n      source  = "${source}"\n      version = "= ${version}"\n    }\n  }\n}\n`,
  );
  terraform(
    ['providers', 'lock', ...platforms.map((platform) => `-platform=${platform}`)],
    directory,
  );
  return readFileSync(join(directory, LOCK_FILE), 'utf8');
}
