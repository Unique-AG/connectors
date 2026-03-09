import { CACHE_MANAGER } from '@nestjs/cache-manager';
import { Inject, Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Cache } from 'cache-manager';
import { eq } from 'drizzle-orm';
import type { UniqueConfigNamespaced } from '~/config';
import { DRIZZLE, DrizzleDatabase } from '../drizzle/drizzle.module';
import { userProfiles } from '../drizzle/schema';
import type { UniqueIdentity } from './unique-identity.types';
import { UniqueUserService } from './unique-user.service';

@Injectable()
export class UniqueUserMappingService {
  public constructor(
    @Inject(DRIZZLE) private readonly drizzle: DrizzleDatabase,
    @Inject(CACHE_MANAGER) private readonly cacheManager: Cache,
    private readonly config: ConfigService<UniqueConfigNamespaced, true>,
    private readonly userService: UniqueUserService,
  ) {}

  public async resolve(userProfileId: string): Promise<UniqueIdentity> {
    const cacheKey = `unique_identity:${userProfileId}`;
    const cached = await this.cacheManager.get<UniqueIdentity>(cacheKey);
    if (cached) return cached;

    const profile = await this.drizzle.query.userProfiles.findFirst({
      where: eq(userProfiles.id, userProfileId),
    });

    if (!profile?.email) {
      throw new Error(`User profile ${userProfileId} has no email`);
    }

    const uniqueUser = await this.userService.findUserByEmail(profile.email);
    if (!uniqueUser) {
      throw new Error(`User not found in Unique for email: ${profile.email}`);
    }

    const headers = this.config.get('unique.serviceExtraHeaders', { infer: true });
    const companyId = headers['x-company-id'] ?? '';

    const identity: UniqueIdentity = {
      userId: uniqueUser.id,
      companyId,
    };

    await this.cacheManager.set(cacheKey, identity);
    return identity;
  }
}
