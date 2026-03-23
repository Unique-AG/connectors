import { Injectable, type NestInterceptor, type ExecutionContext, type CallHandler } from '@nestjs/common';
import { type Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { z } from 'zod';
import { formatToolResult } from '../serialization/format-tool-result.js';
import type { ToolWireResult } from '../serialization/format-tool-result.js';

@Injectable()
export class McpSerializationInterceptor implements NestInterceptor<unknown, ToolWireResult> {
  public constructor(private readonly outputSchema?: z.ZodObject<z.ZodRawShape>) {}

  public intercept(_context: ExecutionContext, next: CallHandler<unknown>): Observable<ToolWireResult> {
    return next.handle().pipe(
      map((value: unknown) => formatToolResult(value, this.outputSchema)),
    );
  }
}
