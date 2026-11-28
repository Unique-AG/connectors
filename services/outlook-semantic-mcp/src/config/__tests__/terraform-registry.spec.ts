import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { BASE_PERMISSIONS, UNIQUE_MODE_PERMISSIONS } from '../graph-permissions';
import {
  renderTerraformRegistry,
  renderTerraformSelectionTests,
  TERRAFORM_REGISTRY_PATH,
  TERRAFORM_SELECTION_TESTS_PATH,
} from '../terraform-registry';

describe('the Entra module registry', () => {
  it('matches the committed file; run `pnpm terraform:registry` after changing a permission or a tool', async () => {
    await expect(renderTerraformRegistry()).toMatchFileSnapshot(
      path.resolve(__dirname, '../../..', TERRAFORM_REGISTRY_PATH),
    );
  });

  it('matches the committed selection tests; run `pnpm terraform:registry` after changing the permission rule', async () => {
    await expect(renderTerraformSelectionTests()).toMatchFileSnapshot(
      path.resolve(__dirname, '../../..', TERRAFORM_SELECTION_TESTS_PATH),
    );
  });

  it('needs no mode input because Unique mode adds no permission beyond the base ones', () => {
    expect(BASE_PERMISSIONS).toEqual(expect.arrayContaining([...UNIQUE_MODE_PERMISSIONS]));
  });
});
