import assert from "node:assert";
import { GraphMessage } from "./microsoft-graph.dtos";
import { createHash } from "node:crypto";
import { isNonNullish, sort } from "remeda";

export const getPossibleUniqueIds = (
  message: Pick<
    GraphMessage,
    | "internetMessageId"
    | "id"
    | "uniqueBody"
    | "from"
    | "toRecipients"
    | "sentDateTime"
    | "subject"
    | "isDraft"
  >,
): string => {
  const internetId = `InternetMessageId:${message.internetMessageId}`;
  const draftKey = `DraftMessageMicrosoftId:${message.id}`;
  // if (message.internetMessageId) {
  //   return `InternetMessageId:${message.internetMessageId}`;
  // }

  if (message.isDraft) {
    return `DraftMessageMicrosoftId:${message.id}`;
  }

  const toRecipients =
    message.toRecipients
      ?.map((item) => item.emailAddress?.address)
      .filter(isNonNullish) ?? [];

  // assert.ok(message.uniqueBody, `Unique body missing`);
  const fingerprint = [
    ["from", message.from?.emailAddress],
    ["to", toRecipients.sort().join(",")],
    [""],
  ]
    .map((item) => item.join(":"))
    .join(`|`);

  return `Fingerprint:${createHash("sha256").update(fingerprint).digest("hex")}`;
};
