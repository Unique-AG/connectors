import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { Metrics } from '../../../metrics';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';

export const GetExternalUserPreferencesInputSchema = z.object({
  recordId: z.string().optional().describe('Unique identifier of an entity'),
});

export type GetExternalUserPreferencesInput = z.infer<typeof GetExternalUserPreferencesInputSchema>;

export const GetExternalUserPreferencesOutputSchema = z
  .object({
    success: z.boolean(),
    data: z.unknown().optional(),
    statusCode: z.number().optional(),
    message: z.string().optional(),
  })
  .loose();

export type GetExternalUserPreferencesResult = z.infer<
  typeof GetExternalUserPreferencesOutputSchema
>;

@Injectable()
export class GetExternalUserPreferencesQuery {
  private readonly logger = new Logger(GetExternalUserPreferencesQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(
    input: GetExternalUserPreferencesInput,
  ): Promise<GetExternalUserPreferencesResult> {
    this.logger.debug({}, 'get_external_user_preferences: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const data = await this.client.get<unknown>('/party/externalUsers/externalUserPreferences', {
        recordId: input.recordId,
      });
      return { success: true, data };
    } catch (err) {
      result = 'error';
      if (err instanceof TemenosApiError) {
        return { success: false, statusCode: err.status, message: err.message };
      }
      throw err;
    } finally {
      this.metrics.recordToolDuration('get_external_user_preferences', result, start);
    }
  }
}
