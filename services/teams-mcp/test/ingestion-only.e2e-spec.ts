import type { INestApplication } from '@nestjs/common';
import { Test, type TestingModule } from '@nestjs/testing';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

/**
 * Boots the app in ingestion-only mode (CHAT_INTEGRATION=disabled,
 * UNIQUE_INTEGRATION=enabled) and asserts that KB/transcript tools are wired
 * while chat/messaging tools are not. Module gating reads process.env at
 * import time, so the toggles are set before AppModule is imported.
 */
describe('Ingestion-only mode (e2e)', () => {
  let app: INestApplication;
  // biome-ignore lint/suspicious/noExplicitAny: DI tokens resolved dynamically for the assertion helper.
  let SendChatMessageTool: any;
  // biome-ignore lint/suspicious/noExplicitAny: DI tokens resolved dynamically for the assertion helper.
  let StartKbIntegrationTool: any;

  beforeAll(async () => {
    process.env.CHAT_INTEGRATION = 'disabled';
    process.env.UNIQUE_INTEGRATION = 'enabled';

    const { AppModule } = await import('../src/app.module');
    const { shouldRegisterKbIntegrationModule } = await import(
      '../src/kb-integration/kb-integration.module'
    );
    const { RootScopeBootstrapService } = await import(
      '../src/unique/root-scope-bootstrap.service'
    );
    ({ SendChatMessageTool } = await import('../src/chat/tools'));
    ({ StartKbIntegrationTool } = await import('../src/transcript/tools'));

    let testingModule = Test.createTestingModule({ imports: [AppModule] });

    // Ingestion is enabled here, so stub the root-scope bootstrap hook that would
    // otherwise require a live Unique API at app.init().
    if (shouldRegisterKbIntegrationModule()) {
      testingModule = testingModule
        .overrideProvider(RootScopeBootstrapService)
        .useValue({ onApplicationBootstrap: () => Promise.resolve() });
    }

    const moduleFixture: TestingModule = await testingModule.compile();
    app = moduleFixture.createNestApplication();
    await app.init();
  });

  afterAll(async () => {
    await app?.close();
    delete process.env.CHAT_INTEGRATION;
  });

  const isRegistered = (token: unknown): boolean => {
    try {
      return app.get(token, { strict: false }) != null;
    } catch {
      return false;
    }
  };

  it('registers KB/transcript tools', () => {
    expect(isRegistered(StartKbIntegrationTool)).toBe(true);
  });

  it('does not register chat/messaging tools', () => {
    expect(isRegistered(SendChatMessageTool)).toBe(false);
  });
});
