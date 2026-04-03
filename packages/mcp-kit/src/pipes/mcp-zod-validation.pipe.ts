import { Injectable, type PipeTransform } from '@nestjs/common';
import { z } from 'zod';
import { McpValidationError } from '../errors/failures.js';

/**
 * NestJS pipe that validates incoming tool arguments against a Zod schema before
 * they reach the handler. Bind it per-handler using `@UsePipes()` or `@Param()`.
 */
@Injectable()
export class McpZodValidationPipe implements PipeTransform {
  /** @param schema The Zod object schema the incoming arguments must satisfy. */
  public constructor(private readonly schema: z.ZodObject<z.ZodRawShape>) {}

  /**
   * Parses and coerces `value` through the schema.
   * Throws `McpValidationError` if validation fails so the MCP framework can
   * surface a structured error response to the client.
   */
  public transform(value: unknown): unknown {
    const result = this.schema.safeParse(value);
    if (!result.success) {
      throw new McpValidationError(`Invalid input: ${result.error.message}`);
    }
    return result.data;
  }
}
