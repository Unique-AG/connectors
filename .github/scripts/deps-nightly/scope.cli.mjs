import assert from 'node:assert';
import { readFileSync } from 'node:fs';
import { commitScope } from './scope.mjs';

const files = readFileSync(0, 'utf8').split('\n').filter(Boolean);
assert.ok(files.length > 0, 'No file paths on stdin');
process.stdout.write(commitScope(files, readFileSync('.gitcommitizen', 'utf8')));
