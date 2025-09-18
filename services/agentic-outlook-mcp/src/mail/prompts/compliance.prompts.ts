import { Prompt } from '@unique-ag/mcp-server-module';
import { Injectable, Scope } from '@nestjs/common';
import * as z from 'zod';

const ToneRiskReviewSchema = z.object({
  draftMessageId: z.string().describe('Draft message ID').meta({ title: 'Draft Message ID' }),
  riskChecklist: z
    .string()
    .describe(
      'Checklist as a comma-separated string, e.g., "promissory language, MNPI, suitability"',
    )
    .meta({ title: 'Risk Checklist' }),
});

const PiiRedactionSchema = z.object({
  draftMessageId: z.string().describe('Draft message ID').meta({ title: 'Draft Message ID' }),
  piiRules: z
    .string()
    .describe('PII types as a comma-separated string, e.g., "SSN, account #, DOB"')
    .meta({ title: 'PII Rules' }),
});

const PhishingSchema = z.object({
  messageId: z
    .string()
    .describe('Message ID to analyze for phishing')
    .meta({ title: 'Message ID' }),
});

@Injectable({ scope: Scope.REQUEST })
export class CompliancePrompts {
  @Prompt({
    name: 'compliance-tone-risk-review',
    title: 'Compliance: Tone & Risk Review',
    description: 'Review a draft for tone and compliance risks with suggested edits',
    parameters: ToneRiskReviewSchema,
    _meta: {
      'unique.app/category': 'Compliance',
    },
  })
  public toneRiskReview({ draftMessageId, riskChecklist }: z.infer<typeof ToneRiskReviewSchema>) {
    const checks = riskChecklist;
    return {
      description: 'Detect tone/risk issues and suggest edits',
      messages: [
        {
          role: 'user' as const,
          content: {
            type: 'text' as const,
            text:
              `Review draft ${draftMessageId} (get-mail-message) for: ${checks}. ` +
              `Return issues with severity, quotes, and suggested edits.`,
          },
        },
      ],
    };
  }

  @Prompt({
    name: 'compliance-pii-redaction',
    title: 'Compliance: PII Redaction',
    description: 'Identify and redact PII in a draft content',
    parameters: PiiRedactionSchema,
    _meta: {
      'unique.app/category': 'Compliance',
    },
  })
  public piiRedaction({ draftMessageId, piiRules }: z.infer<typeof PiiRedactionSchema>) {
    const rules = piiRules;
    return {
      description: 'Propose redactions for PII and produce a redacted version',
      messages: [
        {
          role: 'user' as const,
          content: {
            type: 'text' as const,
            text:
              `Identify and propose redactions for PII per rules (${rules}) in draft ${draftMessageId} (get-mail-message). ` +
              `Output a redacted version and a changelog.`,
          },
        },
      ],
    };
  }

  @Prompt({
    name: 'risk-phishing-suspect',
    title: 'Risk: Phishing Analysis',
    description: 'Analyze an email for phishing/fraud red flags and recommend an action',
    parameters: PhishingSchema,
    _meta: {
      'unique.app/category': 'Risk',
    },
  })
  public phishingAnalysis({ messageId }: z.infer<typeof PhishingSchema>) {
    return {
      description: 'Assess phishing risk with a numeric score and advice',
      messages: [
        {
          role: 'user' as const,
          content: {
            type: 'text' as const,
            text:
              `Analyze ${messageId} (get-mail-message) for phishing red flags (spoofing, urgent requests, mismatched links). ` +
              `Provide a risk score (0-100) and recommended action.`,
          },
        },
      ],
    };
  }
}
