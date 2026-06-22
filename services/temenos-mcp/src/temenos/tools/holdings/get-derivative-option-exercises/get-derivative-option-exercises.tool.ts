import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import { GetDerivativeOptionExercisesInputSchema, GetDerivativeOptionExercisesOutputSchema, GetDerivativeOptionExercisesQuery, type GetDerivativeOptionExercisesResult } from './get-derivative-option-exercises.query';
import { META } from './get-derivative-option-exercises-tool.meta';

@Injectable()
export class GetDerivativeOptionExercisesTool {
  public constructor(private readonly query: GetDerivativeOptionExercisesQuery) {}

  @Tool({
    name: 'get_derivative_option_exercises',
    title: 'Get Derivative Option Exercises',
    description: 'Retrieve derivative option exercise operations from Temenos.',
    parameters: GetDerivativeOptionExercisesInputSchema,
    outputSchema: GetDerivativeOptionExercisesOutputSchema,
    annotations: {
      title: 'Get Derivative Option Exercises',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getDerivativeOptionExercises(
    input: z.infer<typeof GetDerivativeOptionExercisesInputSchema>,
    _context: Context,
  ): Promise<GetDerivativeOptionExercisesResult> {
    return this.query.run(input as never);
  }
}
