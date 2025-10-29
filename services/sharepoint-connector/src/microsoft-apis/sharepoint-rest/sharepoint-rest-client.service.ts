import { Inject, Injectable } from '@nestjs/common';
import { Client, Dispatcher, interceptors } from 'undici';
import { SHAREPOINT_REST_HTTP_CLIENT } from '../../http-client.tokens';
import { MicrosoftAuthenticationService } from '../auth/microsoft-authentication.service';
import { createTokenRefreshInterceptor } from './token-refresh.interceptor';

@Injectable()
export class SharepointRestClientService {
  private readonly client: Dispatcher;

  public constructor(
    @Inject(SHAREPOINT_REST_HTTP_CLIENT) httpClient: Client,
    private readonly microsoftAuthenticationService: MicrosoftAuthenticationService,
  ) {
    // TODO: Add metrics middleware with some logging once we start implementing proper metrics
    const interceptorsInCallingOrder = [
      interceptors.redirect({
        maxRedirections: 10,
      }),
      interceptors.retry({
        maxRetries: 3,
      }),
      createTokenRefreshInterceptor(async () =>
        this.microsoftAuthenticationService.getAccessToken('sharepoint-rest'),
      ),
    ];
    this.client = httpClient.compose(interceptorsInCallingOrder.reverse());
  }

  public async request<T>(siteName: string, apiPath: string): Promise<T> {
    const token = await this.microsoftAuthenticationService.getAccessToken('sharepoint-rest');
    const cleanedApiPath = apiPath.startsWith('/') ? apiPath.slice(1) : apiPath;
    const path = `/sites/${siteName}/_api/${cleanedApiPath}`;
    const { statusCode, body } = await this.client.request({
      method: 'GET',
      path,
      headers: {
        'Content-Type': 'application/json;odata=nometadata',
        Accept: 'application/json;odata=nometadata',
        Authorization: `Bearer ${token}`,
      },
    });

    if (statusCode < 200 || statusCode >= 300) {
      throw new Error(`Failed to request SharePoint endpoint ${path}: ${statusCode}`);
    }

    return body.json() as Promise<T>;
  }
}
