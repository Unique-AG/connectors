import { isNullish } from 'remeda';

export const isWithinCooldown = (timestamp: Date | null, cooldownMinutes: number): boolean => {
  if (isNullish(timestamp)) {
    return false;
  }
  const cooldownThreshold = new Date();
  cooldownThreshold.setMinutes(cooldownThreshold.getMinutes() - cooldownMinutes);
  return timestamp > cooldownThreshold;
};
