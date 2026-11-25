import { NamespacedConfigType, registerConfig } from '@proventuslabs/nestjs-zod';
import { z } from 'zod/v4';
import { json } from '~/utils/zod';
import { calendarIntegrationSchema, mcpDebugModeSchema } from './app.config';
import { McpBackendType, mcpBackendSchema } from './mcp-backend-type.config';
import {
  FEATURE_SETTINGS,
  isToolName,
  TOOL_DECLARATIONS,
  TOOL_NAMES,
  type ToolFeature,
  type ToolName,
} from './tool-declarations';

const FeaturesEnvSchema = z.object({
  mcpBackend: mcpBackendSchema,
  calendarIntegration: calendarIntegrationSchema,
  mcpDebugMode: mcpDebugModeSchema,
  delegatedAccessScan: z
    .string()
    .nonempty()
    .describe('Shared mailboxes are on unless DELEGATED_ACCESS_SCAN is "disabled".'),
  mcpTools: json(z.array(z.string()).min(1))
    .optional()
    .describe(
      'JSON array of tool names to register. Unset registers every tool the mode and features offer.',
    ),
});

const FEATURE_ENV_KEYS = {
  mcpBackend: 'MCP_BACKEND',
  calendarIntegration: 'CALENDAR_INTEGRATION',
  mcpDebugMode: 'MCP_DEBUG_MODE',
  delegatedAccessScan: 'DELEGATED_ACCESS_SCAN',
  mcpTools: 'MCP_TOOLS',
} as const satisfies Record<keyof z.input<typeof FeaturesEnvSchema>, string>;

export const FeaturesConfigSchema = FeaturesEnvSchema.transform((env, ctx) => {
  const enabled: Record<ToolFeature, boolean> = {
    uniqueMode: env.mcpBackend === McpBackendType.MicrosoftGraphAndUniqueApi,
    debugMode: env.mcpDebugMode,
    calendar: env.calendarIntegration,
  };
  const missingFeatures = (name: ToolName) =>
    TOOL_DECLARATIONS[name].requires.filter((feature) => !enabled[feature]);

  const listed = env.mcpTools;
  for (const name of listed ?? []) {
    if (!isToolName(name)) {
      ctx.addIssue({
        code: 'custom',
        path: ['mcpTools'],
        input: name,
        message: `unknown tool "${name}"`,
      });
      continue;
    }
    const missing = missingFeatures(name);
    if (missing.length > 0) {
      ctx.addIssue({
        code: 'custom',
        path: ['mcpTools'],
        input: name,
        message: `"${name}" needs ${missing.map((f) => FEATURE_SETTINGS[f]).join(' and ')}`,
      });
    }
  }

  const tools: ReadonlySet<ToolName> = new Set(
    TOOL_NAMES.filter((name) =>
      listed === undefined ? missingFeatures(name).length === 0 : listed.includes(name),
    ),
  );

  return {
    mode: env.mcpBackend,
    calendar: env.calendarIntegration,
    sharedMailboxes: env.delegatedAccessScan !== 'disabled',
    debug: env.mcpDebugMode,
    tools,
  };
});

export type FeaturesConfig = z.output<typeof FeaturesConfigSchema>;

/**
 * Reads the features from `process.env` synchronously, for code that runs when its file loads
 * (tool decorators, module registration). Injected code uses `featuresConfig` instead; both parse
 * the same schema.
 */
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
