import { Injectable, type PipeTransform } from '@nestjs/common';
import { z } from 'zod';
import { McpValidationError } from '../errors/failures.js';

@Injectable()
export class McpZodValidationPipe implements PipeTransform {
  public constructor(private readonly schema: z.ZodObject<z.ZodRawShape>) {}

  public transform(value: unknown): unknown {
    const result = this.schema.safeParse(value);
    if (!result.success) {
      throw new McpValidationError(`Invalid input: ${result.error.message}`);
    }
    return result.data;
  }
}
