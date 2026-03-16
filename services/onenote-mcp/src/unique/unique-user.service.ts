import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type { FetchFn } from '@qfetch/qfetch';
import { Span, TraceService } from 'nestjs-otel';
import type { UniqueConfigNamespaced } from '~/config';
import { normalizeError } from '~/utils/normalize-error';
import { UNIQUE_FETCH, UNIQUE_REQUEST_HEADERS } from './unique.consts';
import {
  type PublicGetUsersRequest,
  PublicGetUsersRequestSchema,
  type PublicUserResult,
  PublicUsersResultSchema,
} from './unique.dtos';

@Injectable()
export class UniqueUserService {
  private readonly logger = new Logger(UniqueUserService.name);
  private readonly apiBaseUrl: string;
  private readonly configuredHeaders: Record<string, string>;

  public constructor(
    @Inject(UNIQUE_FETCH) private readonly fetch: FetchFn,
    @Inject(UNIQUE_REQUEST_HEADERS) configuredHeaders: Record<string, string>,
    private readonly trace: TraceService,
    config: ConfigService<UniqueConfigNamespaced, true>,
  ) {
    this.apiBaseUrl = config.get('unique.apiBaseUrl', { infer: true });
    this.configuredHeaders = configuredHeaders;
  }

  @Span()
  public async findUserByEmail(email: string): Promise<PublicUserResult | null> {
    const span = this.trace.getSpan();

    const fetchByEmailOrUsername = async (
      payloadInput: PublicGetUsersRequest,
    ): Promise<PublicUserResult | null> => {
      const payload = PublicGetUsersRequestSchema.encode(payloadInput);
      const params: Record<string, string> = {};
      for (const [key, value] of Object.entries(payload)) {
        params[key] = String(value);
      }

      this.logger.debug(
        { searchParams: params },
        'Searching for user in Unique system',
      );

      try {
        const query = new URLSearchParams(params).toString();
        const endpoint = `users?${query}`;
        const response = await this.fetch(endpoint);
        const result = PublicUsersResultSchema.parse(await response.json());
        return result.users.at(0) ?? null;
      } catch (err) {
        const normalized = normalizeError(err);
        this.logger.warn(
          {
            endpoint: `${this.apiBaseUrl}/users`,
            searchParams: params,
            configuredHeaders: this.configuredHeaders,
            errorMessage: normalized.message,
            errorName: normalized.name,
          },
          'Failed to locate user in Unique system',
        );
        return null;
      }
    };

    const [userByEmail, userByUserName] = await Promise.all([
      fetchByEmailOrUsername({ email }),
      fetchByEmailOrUsername({ userName: email }),
    ]);

    const userFound = userByEmail ?? userByUserName;

    span?.setAttribute('user_found', !!userFound);
    span?.setAttribute('found_by_email', !!userByEmail);
    span?.setAttribute('found_by_username', !!userByUserName);

    this.logger.debug(
      {
        email,
        found: !!userFound,
        foundByEmail: !!userByEmail,
        foundByUserName: !!userByUserName,
      },
      'Completed user search operation in Unique system',
    );

    return userFound;
  }
}
