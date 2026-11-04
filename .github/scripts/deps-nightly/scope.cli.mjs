import { readFileSync } from 'node:fs';
import { commitScope } from './scope.mjs';

const files = readFileSync(0, 'utf8').split('\n').filter(Boolean);
process.stdout.write(commitScope(files, readFileSync('.gitcommitizen', 'utf8')));
