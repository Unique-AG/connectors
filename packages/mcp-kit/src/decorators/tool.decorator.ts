import { z } from 'zod';
import type { ToolAnnotations } from '@modelcontextprotocol/sdk/types.js';
import { MCP_TOOL_METADATA } from '../constants';
import type { McpIcon } from '../types';

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
    const name = options.name ?? camelToSnakeCase(methodName);

    let parameters: z.ZodObject<z.ZodRawShape>;
    if (!options.parameters) {
      parameters = z.object({});
    } else if (options.parameters instanceof z.ZodType) {
      parameters = options.parameters as z.ZodObject<z.ZodRawShape>;
    } else {
      parameters = z.object(options.parameters as z.ZodRawShape);
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

    Reflect.defineMetadata(MCP_TOOL_METADATA, metadata, descriptor.value!);
  };
}

function camelToSnakeCase(str: string): string {
  return str
    .replace(/([A-Z]+)([A-Z][a-z])/g, '$1_$2')
    .replace(/([a-z\d])([A-Z])/g, '$1_$2')
    .toLowerCase();
}
