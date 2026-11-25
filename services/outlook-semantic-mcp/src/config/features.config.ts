import { NamespacedConfigType, registerConfig } from '@proventuslabs/nestjs-zod';
import { z } from 'zod/v4';
import { mcpDebugModeSchema } from './app.config';
import { McpBackendType, mcpBackendSchema } from './mcp-backend-type.config';
import {
  FEATURE_SETTINGS,
  GRAPH_PERMISSIONS,
  GROUP_REQUIRES,
  type GraphPermission,
  isToolName,
  TOOL_DECLARATIONS,
  TOOL_NAMES,
  type ToolFeature,
  type ToolName,
} from './tool-declarations';

const TOOLS_FORMAT = 'required, a JSON array of tool names such as ["search_emails","open_email"]';
const PERMISSIONS_FORMAT = 'a JSON array of Graph permission names such as ["Mail.ReadWrite"]';

const jsonStringArray = (format: string) =>
  z
    .string({ error: format })
    .transform((value, ctx) => {
      try {
        return JSON.parse(value) as unknown;
      } catch {
        ctx.addIssue({ code: 'custom', input: value, message: format });
        return z.NEVER;
      }
    })
    .pipe(z.array(z.string(), { error: format }));

const FeaturesEnvSchema = z.object({
  mcpBackend: mcpBackendSchema,
  mcpDebugMode: mcpDebugModeSchema,
  mcpTools: jsonStringArray(TOOLS_FORMAT)
    .pipe(z.array(z.string()).nonempty({ error: 'lists no tool' }))
    .describe('JSON array of the tools to register. Required.'),
  delegatedAccessScan: z
    .string()
    .nonempty()
    .describe('Shared mailboxes are on unless DELEGATED_ACCESS_SCAN is "disabled".'),
  additionalGraphPermissions: jsonStringArray(PERMISSIONS_FORMAT)
    .optional()
    .describe(
      'JSON array of Graph permissions requested on top of what the tools and features need.',
    ),
});

const FEATURE_ENV_KEYS = {
  mcpBackend: 'MCP_BACKEND',
  mcpDebugMode: 'MCP_DEBUG_MODE',
  mcpTools: 'MCP_TOOLS',
  delegatedAccessScan: 'DELEGATED_ACCESS_SCAN',
  additionalGraphPermissions: 'MICROSOFT_ADDITIONAL_GRAPH_PERMISSIONS',
} as const satisfies Record<keyof z.input<typeof FeaturesEnvSchema>, string>;

export const FeaturesConfigSchema = FeaturesEnvSchema.transform((env, ctx) => {
  const enabled: Record<ToolFeature, boolean> = {
    uniqueMode: env.mcpBackend === McpBackendType.MicrosoftGraphAndUniqueApi,
    debugMode: env.mcpDebugMode,
  };

  for (const name of env.mcpTools) {
    if (!isToolName(name)) {
      ctx.addIssue({
        code: 'custom',
        path: ['mcpTools'],
        input: name,
        message: `unknown tool "${name}"`,
      });
      continue;
    }
    const missing = GROUP_REQUIRES[TOOL_DECLARATIONS[name].group].filter((f) => !enabled[f]);
    if (missing.length > 0) {
      ctx.addIssue({
        code: 'custom',
        path: ['mcpTools'],
        input: name,
        message: `"${name}" needs ${missing.map((f) => FEATURE_SETTINGS[f]).join(' and ')}`,
      });
    }
  }

  const isGraphPermission = (name: string): name is GraphPermission =>
    (GRAPH_PERMISSIONS as readonly string[]).includes(name);
  const additional = env.additionalGraphPermissions ?? [];
  for (const name of additional.filter((p) => !isGraphPermission(p))) {
    ctx.addIssue({
      code: 'custom',
      path: ['additionalGraphPermissions'],
      input: name,
      message: `unknown permission "${name}"; known: ${GRAPH_PERMISSIONS.join(', ')}`,
    });
  }

  const tools: ReadonlySet<ToolName> = new Set(
    TOOL_NAMES.filter((name) => env.mcpTools.includes(name)),
  );

  return {
    mode: env.mcpBackend,
    tools,
    calendar: [...tools].some((name) => TOOL_DECLARATIONS[name].group === 'calendar'),
    sharedMailboxes: env.delegatedAccessScan !== 'disabled',
    additionalGraphPermissions: additional.filter(isGraphPermission),
  };
});

export type FeaturesConfig = z.output<typeof FeaturesConfigSchema>;

// Synchronous read of the same schema, for code that runs while its file loads.
export function loadFeaturesConfig(env: NodeJS.ProcessEnv = process.env): FeaturesConfig {
  const input = Object.fromEntries(
    Object.entries(FEATURE_ENV_KEYS).map(([field, key]) => [field, env[key]]),
  );
  const parsed = FeaturesConfigSchema.safeParse(input);
  if (!parsed.success) {
    const issues = parsed.error.issues.map((issue) => {
      const field = issue.path[0] as keyof typeof FEATURE_ENV_KEYS | undefined;
      return field ? `${FEATURE_ENV_KEYS[field]}: ${issue.message}` : issue.message;
    });
    throw new TypeError(`Invalid config for "features":\n${issues.join('\n')}`);
  }
  return parsed.data;
}

export const featuresConfig = registerConfig('features', FeaturesConfigSchema, {
  whitelistKeys: new Set(Object.values(FEATURE_ENV_KEYS)),
});

export type FeaturesConfigNamespaced = NamespacedConfigType<typeof featuresConfig>;
