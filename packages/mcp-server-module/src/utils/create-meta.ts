export const createMeta = (input: {
  icon?: string;
  systemPrompt?: string;
  userPrompt?: string;
  toolFormatInformation?: string;
  category?: string;
}): Record<string, string> => {
  const output: Record<string, string> = {};
  if (input.icon) {
    output['unique.app/icon'] = input.icon;
  }
  if (input.category) {
    output['unique.app/category'] = input.category;
  }
  if (input.systemPrompt) {
    output['unique.app/system-prompt'] = input.systemPrompt;
  }
  if (input.userPrompt) {
    output['unique.app/user-prompt'] = input.userPrompt;
  }
  if (input.toolFormatInformation) {
    output['unique.app/tool-format-information'] = input.toolFormatInformation;
  }
  return output;
};
