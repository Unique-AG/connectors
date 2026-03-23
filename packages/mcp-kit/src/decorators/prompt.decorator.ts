import { z } from 'zod';
import { toKebabCase } from 'remeda';
import { MCP_PROMPT_METADATA } from '../constants';
import type { McpIcon } from '../types';
import { invariant } from '../errors/defect.js';

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
    const name = options.name ?? toKebabCase(methodName);

    let parameters: z.ZodObject<z.ZodRawShape> | undefined;
    if (options.parameters) {
      if (options.parameters instanceof z.ZodObject) {
        parameters = options.parameters;
      } else {
        parameters = z.object(options.parameters);
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

    const method = descriptor.value;
    invariant(method !== undefined, '@Prompt() must be applied to a method');
    Reflect.defineMetadata(MCP_PROMPT_METADATA, metadata, method);
  };
}

