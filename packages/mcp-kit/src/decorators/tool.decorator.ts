import { z } from 'zod';
import type { ToolAnnotations } from '@modelcontextprotocol/sdk/types.js';
import { toSnakeCase } from 'remeda';
import { MCP_TOOL_METADATA } from '../constants';
import type { McpIcon } from '../types';
import { invariant } from '../errors/defect.js';

export interface ToolOptions {
  name?: string;
  title?: string;
  description: string;
  parameters?: z.ZodObject<z.ZodRawShape> | Record<string, z.ZodType>;
  outputSchema?: z.ZodObject<z.ZodRawShape>;
  annotations?: Partial<ToolAnnotations>;
  meta?: Record<string, unknown>;
  timeout?: number;
  mask?: boolean;
  icons?: McpIcon[];
  version?: string | number;
}

export interface ToolMetadata {
  name: string;
  title?: string;
  description: string;
  parameters: z.ZodObject<z.ZodRawShape>;
  outputSchema?: z.ZodObject<z.ZodRawShape>;
  annotations: ToolAnnotations;
  meta?: Record<string, unknown>;
  icons?: McpIcon[];
  version?: string | number;
  timeout?: number;
  mask?: boolean;
  methodName: string;
}

export function Tool(options: ToolOptions): MethodDecorator {
  return (target, propertyKey, descriptor) => {
    const methodName = String(propertyKey);
    const name = options.name ?? toSnakeCase(methodName);

    let parameters: z.ZodObject<z.ZodRawShape>;
    if (!options.parameters) {
      parameters = z.object({});
    } else if (options.parameters instanceof z.ZodObject) {
      parameters = options.parameters;
    } else {
      parameters = z.object(options.parameters);
    }

    const annotations: ToolAnnotations = {
      ...options.annotations,
      title: options.annotations?.title ?? options.title,
    };

    const metadata: ToolMetadata = {
      name,
      title: options.title,
      description: options.description,
      parameters,
      outputSchema: options.outputSchema,
      annotations,
      meta: options.meta,
      icons: options.icons,
      version: options.version,
      timeout: options.timeout,
      mask: options.mask,
      methodName,
    };

    const method = descriptor.value;
    invariant(method !== undefined, '@Tool() must be applied to a method');
    Reflect.defineMetadata(MCP_TOOL_METADATA, metadata, method);
  };
}

