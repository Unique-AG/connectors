import assert from 'node:assert';
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { runOrThrow, sandboxEnv } from './run.mjs';

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

export function mergeLockBlock(existing, generated, constraint) {
  const [fresh] = blocksOf(generated);
  assert.ok(fresh, 'Terraform wrote no provider block.');
  const block = fresh.text.replace(
    /^(\s*constraints\s*=\s*")[^"]*(")/m,
    (_, before, after) => `${before}${constraint}${after}`,
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
