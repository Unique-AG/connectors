import { Prisma, PrismaClient } from '@generated/prisma';
import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { PrismaPg } from '@prisma/adapter-pg';
import { AppConfig, AppSettings } from '../app-settings.enum';
import { createIdPrefixExtension } from './id-prefix.extension';

const prefixMap: Record<Prisma.DMMF.Model['name'], string> = {
  OAuthClient: 'oauth_client',
  AuthorizationCode: 'auth_code',
  OAuthSession: 'oauth_session',
  UserProfile: 'user_profile',
  Token: 'token',
};

@Injectable()
export class PrismaProvider extends PrismaClient {
  public constructor(config: ConfigService<AppConfig, true>) {
    const adapter = new PrismaPg({ connectionString: config.get(AppSettings.DATABASE_URL) });
    super({ adapter: adapter as any });
  }

  public withExtensions() {
    return this.$extends(createIdPrefixExtension(prefixMap));
  }
}
