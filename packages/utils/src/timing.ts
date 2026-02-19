export function elapsedMilliseconds(startTime: Date | number): number {
  const startTimestamp = new Date(startTime).getTime();
  return Date.now() - startTimestamp;
}

export function elapsedSeconds(startTime: Date | number): number {
  return elapsedMilliseconds(startTime) / 1000;
}

export function elapsedSecondsLog(startTime: Date | number): string {
  return `${elapsedSeconds(startTime).toFixed(2)}s`;
}
