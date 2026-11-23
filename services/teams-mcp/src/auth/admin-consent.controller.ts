import { Controller, Get, type HttpRedirectResponse, HttpStatus, Redirect } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type { MicrosoftConfigNamespaced } from '~/config';

// Admin consent needs a work or school directory. Personal accounts, which `common` and `consumers`
// admit, cannot grant it, so every alias falls back to `organizations`, as the Terraform module's
// admin_consent_url does.
const TENANT_ALIASES = new Set(['common', 'organizations', 'consumers']);

@Controller()
export class AdminConsentController {
  private readonly adminConsentUrl: string;

  public constructor(configService: ConfigService<MicrosoftConfigNamespaced, true>) {
    this.adminConsentUrl = this.buildAdminConsentUrl({
      clientId: configService.get('microsoft.clientId', { infer: true }),
      signInTenantId: configService.get('microsoft.signInTenantId', { infer: true }),
      redirectUri: configService.get('microsoft.adminConsentRedirectUri', { infer: true }),
    });
  }

  @Get('admin/consent')
  @Redirect()
  public adminConsent(): HttpRedirectResponse {
    return { url: this.adminConsentUrl, statusCode: HttpStatus.FOUND };
  }

  private buildAdminConsentUrl({
    clientId,
    signInTenantId,
    redirectUri,
  }: {
    clientId: string;
    signInTenantId: string;
    redirectUri: string;
  }): string {
    const tenant = TENANT_ALIASES.has(signInTenantId.toLowerCase())
      ? 'organizations'
      : signInTenantId;
    const url = new URL(
      `/${encodeURIComponent(tenant)}/v2.0/adminconsent`,
      'https://login.microsoftonline.com',
    );
    url.search = new URLSearchParams({
      client_id: clientId,
      scope: 'https://graph.microsoft.com/.default',
      redirect_uri: redirectUri,
    }).toString();
    return url.toString();
  }
}
