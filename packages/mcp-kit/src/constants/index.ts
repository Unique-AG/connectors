/**
 * Symbol constants used for decorator metadata keys and NestJS injection tokens.
 * Symbols are used instead of strings to prevent accidental key collisions.
 */

// Metadata symbol keys — attached to class/method/parameter targets by decorators

/** Metadata key for storing tool registration options on a method. */
export const MCP_TOOL_METADATA = Symbol('MCP_TOOL_METADATA');

/** Metadata key for storing resource registration options on a method. */
export const MCP_RESOURCE_METADATA = Symbol('MCP_RESOURCE_METADATA');

/** Metadata key for storing prompt registration options on a method. */
export const MCP_PROMPT_METADATA = Symbol('MCP_PROMPT_METADATA');

/** Metadata key recording which parameter index receives the MCP context object. */
export const MCP_CTX_PARAM_INDEX = Symbol('MCP_CTX_PARAM_INDEX');

/** Metadata key listing parameter indices that should be excluded from schema generation. */
export const MCP_EXCLUDED_PARAMS = Symbol('MCP_EXCLUDED_PARAMS');

/** Metadata key for storing argument-completion handler metadata on a method. */
export const MCP_COMPLETION_METADATA = Symbol('MCP_COMPLETION_METADATA');

/** Metadata key for OAuth scopes required to invoke a tool or resource. */
export const MCP_REQUIRED_SCOPES = Symbol('MCP_REQUIRED_SCOPES');

// Injection tokens — used with NestJS DI to resolve module-level providers

/** Injection token for the options object passed to `McpModule.forRoot()`. */
export const MCP_MODULE_OPTIONS = Symbol('MCP_MODULE_OPTIONS');

/** Injection token for the session store provider. */
export const MCP_SESSION_STORE = Symbol('MCP_SESSION_STORE');

/** Injection token for the task store provider used by long-running tools. */
export const MCP_TASK_STORE = Symbol('MCP_TASK_STORE');

/** Injection token for the OAuth/auth provider implementation. */
export const MCP_AUTH_PROVIDER = Symbol('MCP_AUTH_PROVIDER');
