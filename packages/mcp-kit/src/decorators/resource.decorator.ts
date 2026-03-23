import { filter, map, pipe } from 'remeda';
import { MCP_RESOURCE_METADATA } from '../constants';
import type { Icon } from '@modelcontextprotocol/sdk/types.js';
import { invariant } from '../errors/defect.js';

/** Options passed to the `@Resource()` decorator. */
export interface ResourceOptions {
  /**
   * RFC 6570 URI or URI template (e.g. `"files://{+path}"`, `"repo://{owner}/{repo}"`).
   * The presence of template expressions determines whether the resource is registered
   * as static or as a URI template. Supports `{param}` and `{+param}` (cross-slash wildcard).
   */
  uri: string;
  /** MCP resource name; defaults to the method name. */
  name?: string;
  description?: string;
  /** MIME type of the content returned by the handler (e.g. `"application/json"`). */
  mimeType?: string;
  icons?: Icon[];
  /** Arbitrary key/value metadata passed through to the registered resource record. */
  meta?: Record<string, unknown>;
  version?: string | number;
  annotations?: {
    /** Hint that the resource never modifies state. */
    readOnlyHint?: boolean;
    /** Hint that repeated fetches with the same URI yield the same result. */
    idempotentHint?: boolean;
  };
}

/**
 * Resolved metadata stored on the method via `Reflect.defineMetadata` after `@Resource()` is applied.
 * `kind` and `templateParams` are derived automatically from the URI string.
 */
export interface ResourceMetadata {
  uri: string;
  name: string;
  description?: string;
  mimeType?: string;
  /** `'static'` when the URI contains no variables; `'template'` otherwise. */
  kind: 'static' | 'template';
  /** Variable names extracted from `{param}` / `{+param}` segments (operator prefixes stripped). */
  templateParams: string[];
  icons?: Icon[];
  meta?: Record<string, unknown>;
  version?: string | number;
  annotations?: {
    readOnlyHint?: boolean;
    idempotentHint?: boolean;
  };
  /** Name of the decorated class method, used to locate and invoke the handler at runtime. */
  methodName: string;
}

/**
 * Marks a class method as an MCP resource handler and stores its resolved {@link ResourceMetadata}
 * on the method via `Reflect.defineMetadata` (key: `MCP_RESOURCE_METADATA`).
 * Static vs. template registration is inferred automatically from the URI.
 */
export function Resource(options: ResourceOptions): MethodDecorator {
  return (target, propertyKey, descriptor) => {
    const methodName = String(propertyKey);
    const templateParams = parseUriTemplate(options.uri);
    const kind: 'static' | 'template' = templateParams.length > 0 ? 'template' : 'static';

    const metadata: ResourceMetadata = {
      uri: options.uri,
      name: options.name ?? methodName,
      description: options.description,
      mimeType: options.mimeType,
      kind,
      templateParams,
      icons: options.icons,
      meta: options.meta,
      version: options.version,
      annotations: options.annotations,
      methodName,
    };

    const method = descriptor.value;
    invariant(method !== undefined, '@Resource() must be applied to a method');
    Reflect.defineMetadata(MCP_RESOURCE_METADATA, metadata, method);
  };
}

/** RFC 6570 single-character operator prefixes on path expressions. */
const RFC6570_OPERATORS = new Set(['+', '#', '.', '/', ';']);

/**
 * Parses an RFC 6570 URI template and returns the extracted variable names.
 * Strips operator prefixes (`+`, `#`, etc.) and trailing `*` so names are always clean identifiers.
 * Splits on `{` to extract expressions without regex.
 */
function parseUriTemplate(uri: string): string[] {
  return pipe(
    uri.split('{').slice(1),
    map((s) => s.slice(0, s.indexOf('}'))),
    filter((e) => e.length > 0),
    map((e) => (RFC6570_OPERATORS.has(e[0]) ? e.slice(1) : e).replace(/\*$/, '')),
  );
}
