import { CACHE_MANAGER } from '@nestjs/cache-manager';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Cache } from 'cache-manager';
import { eq } from 'drizzle-orm';
import { Span, TraceService } from 'nestjs-otel';
import type { UniqueConfigNamespaced } from '~/config';
import { DRIZZLE, type DrizzleDatabase } from '~/drizzle';
import { userProfiles } from '~/drizzle/schema/user-profiles.table';
import type { UniqueIdentity } from './unique-identity.types';
import { UniqueUserService } from './unique-user.service';

const CACHE_PREFIX = 'unique_identity:';

@Injectable()
export class UniqueUserMappingService {
  private readonly logger = new Logger(UniqueUserMappingService.name);

  public constructor(
    @Inject(DRIZZLE) private readonly drizzle: DrizzleDatabase,
    @Inject(CACHE_MANAGER) private readonly cache: Cache,
    private readonly config: ConfigService<UniqueConfigNamespaced, true>,
    private readonly userService: UniqueUserService,
    private readonly trace: TraceService,
  ) {}

  /**
   * Resolves a user profile ID (internal) to a Unique platform identity.
   * Results are cached indefinitely (Unique user IDs don't change). Throws if the user cannot be resolved.
   */
  @Span()
  public async resolve(userProfileId: string): Promise<UniqueIdentity> {
    const span = this.trace.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);

    const cacheKey = `${CACHE_PREFIX}${userProfileId}`;
    const cached = await this.cache.get<UniqueIdentity>(cacheKey);

    if (cached) {
      span?.setAttribute('cache_hit', true);
      return cached;
    }

    span?.setAttribute('cache_hit', false);

    const [profile] = await this.drizzle
      .select({ email: userProfiles.email })
      .from(userProfiles)
      .where(eq(userProfiles.id, userProfileId));

    if (!profile?.email) {
      this.logger.warn({ userProfileId }, 'No email found for user profile');
      throw new Error(`Cannot resolve Unique identity: no email for profile ${userProfileId}`);
    }

    const uniqueUser = await this.userService.findUserByEmail(profile.email);

    if (!uniqueUser) {
      this.logger.warn({ userProfileId }, 'User not found in Unique system');
      throw new Error(
        `Cannot resolve Unique identity: user not found for profile ${userProfileId}`,
      );
    }

    // TODO(UN-17569): replace with proper per-user company ID resolution
    const companyId =
      this.config.get('unique.serviceExtraHeaders', { infer: true })['x-company-id'] ?? '';

    const identity: UniqueIdentity = { userId: uniqueUser.id, companyId };
    await this.cache.set(cacheKey, identity);

    this.logger.debug(
      { userProfileId, uniqueUserId: uniqueUser.id },
      'Resolved and cached Unique identity',
    );

    return identity;
  }
}
