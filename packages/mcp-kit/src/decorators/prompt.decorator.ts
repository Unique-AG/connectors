import { z } from 'zod';
import { toKebabCase } from 'remeda';
import { MCP_PROMPT_METADATA } from '../constants';
import type { Icon } from '@modelcontextprotocol/sdk/types.js';
import { invariant } from '../errors/defect.js';

/** Options passed to the `@Prompt()` decorator. */
export interface PromptOptions {
  /** MCP prompt name; defaults to the method name converted to kebab-case. */
  name?: string;
  /** Human-readable display title exposed to clients. */
  title?: string;
  /** Required description shown to the LLM when selecting the prompt. */
  description: string;
  /** Zod schema for the prompt's input arguments; accepts a `ZodObject` or a plain shape record. */
  parameters?: z.ZodObject<z.ZodRawShape> | Record<string, z.ZodType>;
  icons?: Icon[];
  /** Arbitrary key/value metadata passed through to the registered prompt record. */
  meta?: Record<string, unknown>;
  version?: string | number;
}

/**
 * Resolved metadata stored on the method via `Reflect.defineMetadata` after `@Prompt()` is applied.
 * `parameters` is always a `ZodObject` when present (coerced from the options shape if necessary).
 */
export interface PromptMetadata {
  name: string;
  title?: string;
  description: string;
  parameters?: z.ZodObject<z.ZodRawShape>;
  icons?: Icon[];
  meta?: Record<string, unknown>;
  version?: string | number;
  /** Name of the decorated class method, used to locate and invoke the handler at runtime. */
  methodName: string;
}

/**
 * Marks a class method as an MCP prompt handler and stores its resolved {@link PromptMetadata}
 * on the method via `Reflect.defineMetadata` (key: `MCP_PROMPT_METADATA`).
 * The method name is auto-converted to kebab-case when no explicit `name` is provided.
 */
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

