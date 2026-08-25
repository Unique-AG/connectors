import { describe, expect, it, vi } from 'vitest';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { ResolveMailboxTimezoneQuery } from '../resolve-mailbox-timezone.query';

const USER_PROFILE_ID = convertUserProfileIdToTypeId('user_profile_01kqcg8m7teh6sh8tehd2k0byb');

function createQuery(mailboxTimeZone: string | undefined) {
  return new ResolveMailboxTimezoneQuery({
    run: vi.fn().mockResolvedValue(mailboxTimeZone),
  } as never);
}

describe(ResolveMailboxTimezoneQuery.name, () => {
  it('maps a Windows mailbox timezone to IANA and keeps the Outlook id', async () => {
    const query = createQuery('W. Europe Standard Time');

    await expect(query.run(USER_PROFILE_ID)).resolves.toEqual({
      ianaTimeZone: 'Europe/Berlin',
      outlookTimeZone: 'W. Europe Standard Time',
      notes: [],
    });
  });

  it('passes an IANA mailbox timezone through for both clocks', async () => {
    const query = createQuery('Europe/Zurich');

    await expect(query.run(USER_PROFILE_ID)).resolves.toEqual({
      ianaTimeZone: 'Europe/Zurich',
      outlookTimeZone: 'Europe/Zurich',
      notes: [],
    });
  });

  it('falls back to UTC when mailbox settings are missing', async () => {
    const query = createQuery(undefined);

    await expect(query.run(USER_PROFILE_ID)).resolves.toEqual({
      ianaTimeZone: 'UTC',
      outlookTimeZone: 'UTC',
      notes: ['Mailbox timezone was unavailable; times are requested in UTC.'],
    });
  });

  it('falls back to UTC when the mailbox timezone cannot be mapped', async () => {
    const query = createQuery('Customized Time Zone');

    await expect(query.run(USER_PROFILE_ID)).resolves.toEqual({
      ianaTimeZone: 'UTC',
      outlookTimeZone: 'UTC',
      notes: [
        'Mailbox timezone "Customized Time Zone" could not be mapped to IANA; relative windows are resolved in UTC.',
      ],
    });
  });
});
