export function smear(text: string | null | undefined, leaveOver = 4): string {
  if (text === undefined || text === null) {
    return '__erroneous__';
  }
  if (!text.length || text.length <= leaveOver) return '[Smeared]';

  const charsToSmear = text.length - leaveOver;
  if (charsToSmear < 3) return '[Smeared]';

  const end = text.substring(text.length - leaveOver, text.length);
  const toSmear = text.substring(0, text.length - leaveOver);
  return `${toSmear.replaceAll(/[a-zA-Z0-9_]/g, '*')}${end}`;
}
