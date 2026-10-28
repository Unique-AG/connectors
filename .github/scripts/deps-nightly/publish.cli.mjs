import { join } from 'node:path';
import { assertAllowedChanges, assertRequirementEdits, readChanges } from './patch.mjs';
import { readFiles, trackedFiles } from './repo.mjs';
import { runOrThrow } from './run.mjs';

const { ecosystem, members } = JSON.parse(process.env.ENTRY);
const pyprojects = () => readFiles(trackedFiles(/(^|\/)pyproject\.toml$/));
const before = ecosystem === 'uv' ? pyprojects() : {};

runOrThrow('git', ['apply', join(process.env.PATCH_DIR, 'changes.patch')]);
assertAllowedChanges({ ecosystem, ...readChanges() });
assertRequirementEdits({ members, before, after: ecosystem === 'uv' ? pyprojects() : {} });
