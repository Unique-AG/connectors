import assert from 'node:assert';
import { Readable } from 'node:stream';
import { Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { MockAgent } from 'undici';
import { afterEach, beforeEach, describe, expect, it, type Mock, vi } from 'vitest';
import { ProxyService } from '../../proxy';
import { createSmeared } from '../../utils/smeared';
import { MicrosoftAuthenticationService } from '../auth/microsoft-authentication.service';
import {
  isListViewThresholdError,
  SharepointRestError,
  SharepointRestHttpService,
} from './sharepoint-rest-http.service';

describe('SharepointRestHttpService', () => {
  let service: SharepointRestHttpService;
  let request: Mock;

  const siteName = createSmeared('Contoso');

  beforeEach(async () => {
    request = vi.fn();
    const dispatcher = {
      compose: vi.fn().mockReturnValue({ request }),
    };

    const { unit } = await TestBed.solitary(SharepointRestHttpService)
      .mock(ConfigService)
      .impl(() => ({
        get: vi.fn((key: string) => {
          if (key === 'sharepoint.baseUrl') {
            return 'https://contoso.sharepoint.com';
          }
          if (key === 'app.logsDiagnosticsDataPolicy') {
            return 'disclose';
          }
          return undefined;
        }),
      }))
      .mock(MicrosoftAuthenticationService)
      .impl(() => ({
        getAccessToken: vi.fn().mockResolvedValue('token'),
      }))
      .mock(ProxyService)
      .impl(() => ({
        getDispatcher: vi.fn().mockReturnValue(dispatcher),
      }))
      .compile();

    service = unit;
  });

  it('requests a single JSON document under /_api/', async () => {
    request.mockResolvedValue({
      statusCode: 200,
      headers: {},
      body: { json: vi.fn().mockResolvedValue({ ReadSecurity: 1 }) },
    });

    const result = await service.requestSingle<{ ReadSecurity: number }>(
      siteName,
      'sites',
      "web/lists(guid'list-1')?$select=ReadSecurity",
    );

    expect(result).toEqual({ ReadSecurity: 1 });
    expect(request).toHaveBeenCalledWith(
      expect.objectContaining({
        method: 'GET',
        path: "/sites/Contoso/_api/web/lists(guid'list-1')?$select=ReadSecurity",
        headers: expect.objectContaining({
          Accept: 'application/json;odata=nometadata',
        }),
      }),
    );
  });

  it('carries the SharePoint error code and status of a failed request', async () => {
    request.mockResolvedValue({
      statusCode: 500,
      headers: {},
      body: {
        json: vi.fn().mockResolvedValue({
          'odata.error': {
            code: '-2147024860, Microsoft.SharePoint.SPQueryThrottledException',
            message: { lang: 'en-US', value: 'exceeds the list view threshold' },
          },
        }),
      },
    });

    const failure = service.requestSingle(siteName, 'sites', "web/lists(guid'list-1')/items");

    await expect(failure).rejects.toBeInstanceOf(SharepointRestError);
    await expect(failure).rejects.toMatchObject({
      statusCode: 500,
      errorCode: '-2147024860, Microsoft.SharePoint.SPQueryThrottledException',
      message: expect.not.stringContaining('list view threshold'),
    });
    await expect(failure).rejects.toSatisfy(isListViewThresholdError);
  });

  it('fails without an error code when the body is not an OData error', async () => {
    request.mockResolvedValue({
      statusCode: 503,
      headers: {},
      body: { json: vi.fn().mockRejectedValue(new SyntaxError('Unexpected token <')) },
    });

    const failure = service.requestSingle(siteName, 'sites', "web/lists(guid'list-1')");

    await expect(failure).rejects.toMatchObject({ statusCode: 503, errorCode: undefined });
    await expect(failure).rejects.not.toSatisfy(isListViewThresholdError);
  });

  describe('through the real interceptor chain', () => {
    let mockAgent: MockAgent;
    let realService: SharepointRestHttpService;

    beforeEach(async () => {
      mockAgent = new MockAgent();
      mockAgent.disableNetConnect();

      const { unit } = await TestBed.solitary(SharepointRestHttpService)
        .mock(ConfigService)
        .impl(() => ({
          get: vi.fn((key: string) =>
            key === 'sharepoint.baseUrl' ? 'https://contoso.sharepoint.com' : undefined,
          ),
        }))
        .mock(MicrosoftAuthenticationService)
        .impl(() => ({ getAccessToken: vi.fn().mockResolvedValue('token') }))
        .mock(ProxyService)
        .impl(() => ({ getDispatcher: vi.fn().mockReturnValue(mockAgent) }))
        .compile();

      realService = unit;
    });

    afterEach(async () => {
      await mockAgent.close();
    });

    const replyThrottled = (listName = 'Contoso list') =>
      mockAgent
        .get('https://contoso.sharepoint.com')
        .intercept({ path: "/sites/Contoso/_api/web/lists(guid'list-1')/items", method: 'GET' })
        .reply(500, {
          'odata.error': {
            code: '-2147024860, Microsoft.SharePoint.SPQueryThrottledException',
            message: { lang: 'en-US', value: `${listName} exceeds the list view threshold` },
          },
        })
        .times(1);

    const requestItems = () =>
      realService.requestSingle(siteName, 'sites', "web/lists(guid'list-1')/items", {
        retryStatusCodes: [429, 502, 503, 504],
      });

    it('fails on the first throttled response when 500 is not a retried status', async () => {
      replyThrottled();

      await expect(requestItems()).rejects.toSatisfy(isListViewThresholdError);
      mockAgent.assertNoPendingInterceptors();
    });

    it('logs only the error code of a failed request when logs are concealed', async () => {
      replyThrottled('Secret list');

      await expect(requestItems()).rejects.toBeInstanceOf(SharepointRestError);

      const loggerMock = vi.mocked(Logger).mock;
      const interceptorLoggerIndex = loggerMock.calls
        .map(([context]) => context)
        .lastIndexOf('SharepointRestHttpInterceptor');
      const interceptorLogger = loggerMock.instances[interceptorLoggerIndex];
      assert.ok(interceptorLogger, 'The interceptor logger was not created');
      const errorLog = vi.mocked(interceptorLogger.error);
      expect(errorLog).toHaveBeenCalledWith(
        expect.objectContaining({
          msg: 'SharePoint REST request failed with server error',
          errorCode: '-2147024860, Microsoft.SharePoint.SPQueryThrottledException',
        }),
      );
      expect(JSON.stringify(errorLog.mock.calls)).not.toContain('Secret list');
    });
  });

  it('returns the download as a stream', async () => {
    request.mockResolvedValue({
      statusCode: 200,
      headers: {},
      body: Readable.from(['file']),
    });

    const stream = await service.requestDownload(
      siteName,
      'sites',
      "web/lists(guid'list-1')/items(4)/AttachmentFiles('a.pdf')/$value",
    );

    expect(stream).toBeInstanceOf(Readable);
    expect((await stream.toArray()).join('')).toBe('file');
  });
});
