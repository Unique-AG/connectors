import { Injectable, Logger } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import {
  type PublicGetUsersRequest,
  PublicGetUsersRequestSchema,
  type PublicUserResult,
  PublicUsersResultSchema,
} from './unique.dtos';
import { UniqueApiClient } from './unique-api.client';

@Injectable()
export class UniqueUserService {
  private readonly logger = new Logger(UniqueUserService.name);

  public constructor(
    private readonly api: UniqueApiClient,
    private readonly trace: TraceService,
  ) {}

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
        { searchParams: Object.keys(params) },
        'Searching for user in Unique system',
      );

      try {
        const result = PublicUsersResultSchema.parse(await this.api.get('users', params));
        return result.users.at(0) ?? null;
      } catch {
        this.logger.warn({ email }, 'Failed to locate user in Unique system');
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
        found: !!userFound,
        foundByEmail: !!userByEmail,
        foundByUserName: !!userByUserName,
      },
      'Completed user search operation in Unique system',
    );

    return userFound;
  }
}
