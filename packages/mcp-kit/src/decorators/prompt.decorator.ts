import { z } from 'zod';
import { MCP_PROMPT_METADATA } from '../constants';
import type { McpIcon } from '../types';

export interface PromptOptions {
  name?: string;
  title?: string;
  description: string;
  parameters?: z.ZodObject<z.ZodRawShape> | Record<string, z.ZodType>;
  icons?: McpIcon[];
  meta?: Record<string, unknown>;
  version?: string | number;
}

export interface PromptMetadata {
  name: string;
  title?: string;
  description: string;
  parameters?: z.ZodObject<z.ZodRawShape>;
  icons?: McpIcon[];
  meta?: Record<string, unknown>;
  version?: string | number;
  methodName: string;
}

export function Prompt(options: PromptOptions): MethodDecorator {
  return (target, propertyKey, descriptor) => {
    const methodName = String(propertyKey);
    const name = options.name ?? camelToKebabCase(methodName);

    let parameters: z.ZodObject<z.ZodRawShape> | undefined;
    if (options.parameters) {
      if (options.parameters instanceof z.ZodType) {
        parameters = options.parameters as z.ZodObject<z.ZodRawShape>;
      } else {
        parameters = z.object(options.parameters as z.ZodRawShape);
      }
    }

    const metadata: PromptMetadata = {
      name,
      title: options.title,
      description: options.description,
      parameters,
      icons: options.icons,
      meta: options.meta,
      version: options.version,
      methodName,
    };

    Reflect.defineMetadata(MCP_PROMPT_METADATA, metadata, descriptor.value!);
  };
}

function camelToKebabCase(str: string): string {
  return str
    .replace(/([A-Z]+)([A-Z][a-z])/g, '$1-$2')
    .replace(/([a-z\d])([A-Z])/g, '$1-$2')
    .toLowerCase();
}
