// Metadata symbol keys — using Symbols (not strings) to avoid collisions
export const MCP_TOOL_METADATA = Symbol('MCP_TOOL_METADATA');
export const MCP_RESOURCE_METADATA = Symbol('MCP_RESOURCE_METADATA');
export const MCP_PROMPT_METADATA = Symbol('MCP_PROMPT_METADATA');
export const MCP_CTX_PARAM_INDEX = Symbol('MCP_CTX_PARAM_INDEX');
export const MCP_EXCLUDED_PARAMS = Symbol('MCP_EXCLUDED_PARAMS');
export const MCP_COMPLETION_METADATA = Symbol('MCP_COMPLETION_METADATA');
export const MCP_REQUIRED_SCOPES = Symbol('MCP_REQUIRED_SCOPES');

// Injection tokens
export const MCP_MODULE_OPTIONS = Symbol('MCP_MODULE_OPTIONS');
export const MCP_SESSION_STORE = Symbol('MCP_SESSION_STORE');
export const MCP_TASK_STORE = Symbol('MCP_TASK_STORE');
export const MCP_AUTH_PROVIDER = Symbol('MCP_AUTH_PROVIDER');
