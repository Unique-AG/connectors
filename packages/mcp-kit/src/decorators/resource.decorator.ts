import { filter, flatMap, map, pipe } from 'remeda';
import { MCP_RESOURCE_METADATA } from '../constants';
import type { Icon } from '@modelcontextprotocol/sdk/types.js';
import { invariant } from '../errors/defect.js';

/** Options passed to the `@Resource()` decorator. */
export interface ResourceOptions {
  /**
   * RFC 6570 URI or URI template (e.g. `"files://{path*}"`, `"search://{?q,limit}"`).
   * The presence of template or query-parameter expressions determines whether the
   * resource is registered as static or as a URI template.
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
 * `kind`, `templateParams`, and `queryParams` are derived automatically from the URI string.
 */
export interface ResourceMetadata {
  uri: string;
  name: string;
  description?: string;
  mimeType?: string;
  /** `'static'` when the URI contains no variables; `'template'` otherwise. */
  kind: 'static' | 'template';
  /** Path variable names extracted from `{param}` / `{param*}` segments of the URI template. */
  templateParams: string[];
  /** Query variable names extracted from `{?param,…}` segments of the URI template. */
  queryParams: string[];
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
    const { templateParams, queryParams } = parseUriTemplate(options.uri);
    const kind: 'static' | 'template' =
      templateParams.length > 0 || queryParams.length > 0 ? 'template' : 'static';

    const metadata: ResourceMetadata = {
      uri: options.uri,
      name: options.name ?? methodName,
      description: options.description,
      mimeType: options.mimeType,
      kind,
      templateParams,
      queryParams,
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

/**
 * Parses an RFC 6570 URI template and returns the extracted path and query parameter names.
 * Handles simple (`{param}`), exploded (`{param*}`), and query (`{?a,b}`) expressions.
 * Splits on `{` to extract template expressions without regex.
 */
function parseUriTemplate(uri: string): { templateParams: string[]; queryParams: string[] } {
  const expressions = pipe(
    uri.split('{').slice(1),
    map((s) => s.slice(0, s.indexOf('}'))),
  );

  const queryParams = pipe(
    expressions,
    filter((e) => e.startsWith('?')),
    flatMap((e) => e.slice(1).split(',')),
    map((p) => p.trim()),
  );

  const templateParams = filter(expressions, (e) => !e.startsWith('?'));

  return { templateParams, queryParams };
}
