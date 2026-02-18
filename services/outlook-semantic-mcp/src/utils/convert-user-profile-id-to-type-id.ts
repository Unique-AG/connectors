import { fromString, parseTypeId, TypeID, typeid } from 'typeid-js';

export type UserProfileTypeID = TypeID<'user_profile'>;

export const convertUserProfileIdToTypeId = (userProfileId: string): UserProfileTypeID => {
  const tid = fromString(userProfileId, 'user_profile');
  const pid = parseTypeId(tid);
  return typeid(pid.prefix, pid.suffix);
};
