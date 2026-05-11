import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'building',
  systemPrompt:
    'Use when the user needs ownership data: directors / representatives, ultimate beneficial owners, share capital, contact details, or the registry activity declaration. Otherwise `get_lite_profile` covers identification at a lower credit cost. Spends credits — confirm the user wants this depth before calling. A `statusCode: 405` means the enhanced profile is not available synchronously for that jurisdiction; surface that limitation to the user rather than substituting another tool.',
});
