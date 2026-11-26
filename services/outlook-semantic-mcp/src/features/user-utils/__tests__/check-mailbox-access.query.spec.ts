import { describe, expect, it, vi } from 'vitest';
import { loadFeaturesConfig } from '~/config';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { CheckMailboxAccessQuery } from '../check-mailbox-access.query';

const USER_PROFILE_ID = convertUserProfileIdToTypeId('user_profile_01h455vb4pex5vsknk084sn02q');
const OWN_EMAIL = 'ada@example.com';
const OWN_UPN = 'ada.lovelace@example.onmicrosoft.com';

const queryWith = (scan: string) => {
  const getUserProfileQuery = {
    run: vi.fn().mockResolvedValue({ email: OWN_EMAIL, username: OWN_UPN }),
  };
  const query = new CheckMailboxAccessQuery(
    loadFeaturesConfig({
      MCP_BACKEND: 'microsoft_graph',
      MCP_TOOLS: JSON.stringify(['open_email']),
      DELEGATED_ACCESS_SCAN: scan,
    }),
    getUserProfileQuery as never,
  );
  return query;
};

describe(CheckMailboxAccessQuery.name, () => {
  describe('with DELEGATED_ACCESS_SCAN=disabled', () => {
    const query = queryWith('disabled');

    it('allows a call without a mailbox', async () => {
      expect(await query.run(USER_PROFILE_ID, undefined)).toEqual({ allowed: true });
    });

    it.each([OWN_EMAIL, 'Ada@Example.com', OWN_UPN, 'Ada.Lovelace@example.onmicrosoft.com'])(
      "allows the user's own mailbox written as %j",
      async (mailbox) => {
        expect(await query.run(USER_PROFILE_ID, mailbox)).toEqual({ allowed: true });
      },
    );

    it('refuses the own address with surrounding spaces, which Graph would not resolve', async () => {
      expect(await query.run(USER_PROFILE_ID, ` ${OWN_EMAIL} `)).toMatchObject({ allowed: false });
    });

    it('refuses another mailbox, naming the own one', async () => {
      expect(await query.run(USER_PROFILE_ID, 'shared@example.com')).toEqual({
        allowed: false,
        message: `This server works only with your own mailbox (${OWN_EMAIL}). Call the tool again without \`mailbox\`.`,
      });
    });
  });

  it.each(['full_access_only', 'granular_access'])(
    'allows another mailbox with DELEGATED_ACCESS_SCAN=%s',
    async (scan) => {
      expect(await queryWith(scan).run(USER_PROFILE_ID, 'shared@example.com')).toEqual({
        allowed: true,
      });
    },
  );
});
