import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it } from 'vitest';
import { HealthConfig, healthConfig } from './health.config';
import { HealthController } from './health.controller';

describe('HealthController', () => {
  let controller: HealthController;

  beforeEach(async () => {
    const mockHealthConfig: HealthConfig = {
      maxHeapMb: 150,
      version: '1.0.0',
    };

    const { unit } = await TestBed.solitary(HealthController)
      .mock(healthConfig.KEY)
      .impl(() => mockHealthConfig)
      .compile();

    controller = unit;
  });

  it('is defined', () => {
    expect(controller).toBeDefined();
  });
});
