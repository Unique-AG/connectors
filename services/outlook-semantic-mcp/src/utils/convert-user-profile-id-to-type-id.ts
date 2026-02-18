import { fromString, parseTypeId, TypeID, typeid } from 'typeid-js';

export const convertUserProfileIdToTypeId = (userProfileId: string): TypeID<'user_profile'> => {
  const tid = fromString(userProfileId, 'user_profile');
  const pid = parseTypeId(tid);
  return typeid(pid.prefix, pid.suffix);
};
