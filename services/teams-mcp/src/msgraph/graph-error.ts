import { GraphError } from "@microsoft/microsoft-graph-client";
import z from "zod/v4";
import { isoDatetimeToDate } from "~/utils/zod";

/**
 * See docs on {@link https://learn.microsoft.com/en-us/graph/errors for graph errors}.
 */
export const MicrosoftGraphErrorSchema = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    innerError: z
      .object({
        'request-id': z.string(),
        date: isoDatetimeToDate({ offset: true }),
      })
      .optional(),
  }),
});

// https://github.com/microsoftgraph/msgraph-sdk-javascript/blob/db1757abe7a4cad310f0cd4d7d2a83b961390cce/src/GraphErrorHandler.ts#L75-L88
export const makeGraphError = (graphError: z.output<typeof MicrosoftGraphErrorSchema>, statusCode: number, headers?: Headers): GraphError => {
  const error = graphError.error;
  const gError = new GraphError(statusCode, error.message);
  gError.code = error.code;
  if (error.innerError !== undefined) {
    gError.requestId = error.innerError["request-id"];
    gError.date = error.innerError.date;
  }

  gError.body = JSON.stringify(error);
  gError.headers = headers;

  return gError;
}
