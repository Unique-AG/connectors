import { z } from 'zod';
import type { ToolAnnotations } from '@modelcontextprotocol/sdk/types.js';
import { toSnakeCase } from 'remeda';
import { MCP_TOOL_METADATA } from '../constants';
import type { Icon } from '@modelcontextprotocol/sdk/types.js';
import { invariant } from '../errors/defect.js';

/** Options passed to the `@Tool()` decorator. */
export interface ToolOptions {
  /** MCP tool name; defaults to the method name converted to snake_case. */
  name?: string;
  /** Human-readable display title exposed to clients. */
  title?: string;
  /** Required description shown to the LLM when selecting the tool. */
  description: string;
  /** Zod input schema; accepts a `ZodObject` or a plain shape record. Defaults to an empty object. */
  parameters?: z.ZodObject<z.ZodRawShape> | Record<string, z.ZodType>;
  /** Zod schema describing the structured output of the tool, when supported by the client. */
  outputSchema?: z.ZodObject<z.ZodRawShape>;
  /** MCP protocol annotations (e.g. `readOnlyHint`, `destructiveHint`) forwarded verbatim. */
  annotations?: Partial<ToolAnnotations>;
  /** Arbitrary key/value metadata passed through to the registered tool record. */
  meta?: Record<string, unknown>;
  /** Maximum execution time in milliseconds before the tool call is considered timed out. */
  timeout?: number;
  /**
   * When `true`, the tool's output values are masked in logs and traces.
   * Use for tools that return sensitive data such as credentials or PII.
   */
  mask?: boolean;
  icons?: Icon[];
  version?: string | number;
}

/**
 * Resolved metadata stored on the method via `Reflect.defineMetadata` after `@Tool()` is applied.
 * `parameters` is always a `ZodObject` (coerced from the options shape if necessary) and
 * `annotations` is always fully populated (merged from `options.annotations` and `options.title`).
 */
export interface ToolMetadata {
  name: string;
  title?: string;
  description: string;
  parameters: z.ZodObject<z.ZodRawShape>;
  outputSchema?: z.ZodObject<z.ZodRawShape>;
  annotations: ToolAnnotations;
  meta?: Record<string, unknown>;
  icons?: Icon[];
  version?: string | number;
  timeout?: number;
  /** When `true`, tool outputs must be redacted in logs and traces. */
  mask?: boolean;
  /** Name of the decorated class method, used to locate and invoke the handler at runtime. */
  methodName: string;
}

/**
 * Marks a class method as an MCP tool and stores its resolved {@link ToolMetadata}
 * on the method via `Reflect.defineMetadata` (key: `MCP_TOOL_METADATA`).
 * The method name is auto-converted to snake_case when no explicit `name` is provided.
 */
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

