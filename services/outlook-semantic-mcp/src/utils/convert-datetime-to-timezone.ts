export function convertDateTimeToTimezone(
  utcString: string | null | undefined,
  timezone: string | undefined,
): string | null | undefined {
  if (!utcString || !timezone) {
    return utcString;
  }
  try {
    const date = new Date(utcString);
    if (Number.isNaN(date.getTime())) {
      return utcString;
    }

    const parts = new Intl.DateTimeFormat('en', {
      timeZone: timezone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    }).formatToParts(date);

    const get = (type: string) => parts.find((p) => p.type === type)?.value ?? '00';

    // hour12:false can return '24' for midnight on some platforms
    const hour = get('hour') === '24' ? '00' : get('hour');
    const localStr = `${get('year')}-${get('month')}-${get('day')}T${hour}:${get('minute')}:${get('second')}`;

    // Compute the UTC offset by treating the local parts as UTC and comparing to the original
    const offsetMs = Date.parse(`${localStr}Z`) - date.getTime();
    const offsetMin = Math.round(offsetMs / 60000);
    const sign = offsetMin >= 0 ? '+' : '-';
    const absMin = Math.abs(offsetMin);
    const hh = String(Math.floor(absMin / 60)).padStart(2, '0');
    const mm = String(absMin % 60).padStart(2, '0');

    return `${localStr}${sign}${hh}:${mm}`;
  } catch {
    return utcString;
  }
}
