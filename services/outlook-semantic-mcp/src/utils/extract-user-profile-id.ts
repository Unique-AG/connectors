import { McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { UnauthorizedException } from '@nestjs/common';
import { traceAttrs } from '~/email-sync/tracing.utils';
import {
  convertUserProfileIdToTypeId,
  UserProfileTypeID,
} from './convert-user-profile-id-to-type-id';

export const extractUserProfileId = (request: McpAuthenticatedRequest): UserProfileTypeID => {
  const userProfileId = request.user?.userProfileId;
  if (!userProfileId) throw new UnauthorizedException('User not authenticated');

  traceAttrs({ user_profile_id: userProfileId });
  return convertUserProfileIdToTypeId(userProfileId);
};
