import { Prompt } from '@unique-ag/mcp-server-module';
import { Injectable, Scope } from '@nestjs/common';
import * as z from 'zod';

const ProspectOutreachSchema = z.object({
  recipient: z.email().describe('Recipient email address').meta({ title: 'Recipient' }),
  clientName: z.string().describe('Recipient name').meta({ title: 'Client Name' }),
  valueProp: z.string().describe('Short value proposition').meta({ title: 'Value Proposition' }),
  callToAction: z.string().describe('Clear next step').meta({ title: 'Call to Action' }),
});

const MeetingFollowupSchema = z.object({
  recipient: z.email().describe('Recipient email').meta({ title: 'Recipient' }),
  clientName: z.string().describe('Recipient name').meta({ title: 'Client Name' }),
  meetingNotes: z.string().describe('Key points/decisions').meta({ title: 'Meeting Notes' }),
  nextSteps: z
    .string()
    .describe('Action items as a comma-separated list')
    .meta({ title: 'Next Steps' }),
  dueDates: z
    .string()
    .optional()
    .describe('Optional due dates as a comma-separated list')
    .meta({ title: 'Due Dates' }),
});

const KycAmlSchema = z.object({
  recipient: z.email().describe('Recipient email').meta({ title: 'Recipient' }),
  clientName: z.string().describe('Recipient name').meta({ title: 'Client Name' }),
  docChecklist: z
    .string()
    .describe('Required documents as a comma-separated list')
    .meta({ title: 'Document Checklist' }),
  securePortalUrl: z.string().describe('Secure upload URL').meta({ title: 'Secure Upload URL' }),
  supportContact: z.string().describe('Support email/phone').meta({ title: 'Support Contact' }),
});

const RfpCoverSchema = z.object({
  recipient: z.email().describe('Recipient email').meta({ title: 'Recipient' }),
  firmName: z.string().describe('Your firm name').meta({ title: 'Firm Name' }),
  rfpTitle: z.string().describe('RFP title').meta({ title: 'RFP Title' }),
  submissionDeadline: z
    .string()
    .describe('Submission deadline')
    .meta({ title: 'Submission Deadline' }),
  differentiators: z
    .array(z.string())
    .describe('2-3 differentiators')
    .meta({ title: 'Differentiators' }),
});

const InvestorUpdateSchema = z.object({
  recipient: z.email().describe('Recipient email').meta({ title: 'Recipient' }),
  fundName: z.string().describe('Fund name').meta({ title: 'Fund Name' }),
  period: z.string().describe('Reporting period').meta({ title: 'Reporting Period' }),
  performance: z.string().describe('Performance summary').meta({ title: 'Performance Summary' }),
  drivers: z.string().describe('Key drivers as a comma-separated list').meta({ title: 'Drivers' }),
  risks: z.string().describe('Notable risks as a comma-separated list').meta({ title: 'Risks' }),
  disclaimers: z.string().describe('Required disclaimers text').meta({ title: 'Disclaimers' }),
});

const SensitiveInfoRequestSchema = z.object({
  recipient: z.email().describe('Recipient email').meta({ title: 'Recipient' }),
  clientName: z.string().describe('Recipient name').meta({ title: 'Client Name' }),
  infoRequested: z
    .string()
    .describe('Information requested as a comma-separated list')
    .meta({ title: 'Information Requested' }),
  secureMethod: z
    .string()
    .describe('Secure method (portal, encrypted link)')
    .meta({ title: 'Secure Method' }),
  disclaimer: z.string().describe('Compliance disclaimer').meta({ title: 'Disclaimer' }),
});

const IntroductionSchema = z.object({
  toA: z.email().describe('First party email').meta({ title: 'First Email' }),
  toB: z.email().describe('Second party email').meta({ title: 'Second Email' }),
  context: z
    .string()
    .describe('Brief context for intro')
    .meta({ title: 'Brief Context for Intro' }),
  ask: z.string().describe('The ask for the intro').meta({ title: 'The Ask for the Intro' }),
});

const AutoAckSchema = z.object({
  messageId: z.string().describe('Incoming message ID').meta({ title: 'Message ID' }),
  recipient: z.email().describe('Recipient to acknowledge').meta({ title: 'Recipient' }),
  slaHint: z.string().describe('Expected response time hint').meta({ title: 'SLA Hint' }),
});

const FollowupNudgeSchema = z.object({
  recipient: z.email().describe('Recipient email').meta({ title: 'Recipient' }),
  threadQuery: z
    .string()
    .describe('Query to find the last exchange')
    .meta({ title: 'Thread Query' }),
});

const OutOfOfficeSchema = z.object({
  recipient: z.email().describe('Recipient email').meta({ title: 'Recipient' }),
  returnDate: z.string().describe('Return date').meta({ title: 'Return Date' }),
  backupContact: z.string().describe('Backup contact details').meta({ title: 'Backup Contact' }),
});

const TradeConfirmationSummarySchema = z.object({
  messageId: z.string().describe('Trade confirmation message ID').meta({ title: 'Message ID' }),
  recipient: z.email().describe('Recipient email for the summary').meta({ title: 'Recipient' }),
});

const ComplianceEscalationSchema = z.object({
  messageId: z.string().describe('Source message ID with the issue').meta({ title: 'Message ID' }),
  recipient: z.email().describe('Compliance team recipient').meta({ title: 'Recipient' }),
  issueSummary: z
    .string()
    .describe('Short description of the issue')
    .meta({ title: 'Issue Summary' }),
});

const GenericDraftSchema = z.object({
  recipient: z.email().describe('Recipient email').meta({ title: 'Recipient' }),
  subject: z.string().describe('Email subject').meta({ title: 'Subject' }),
});

@Injectable({ scope: Scope.REQUEST })
export class ComposePrompts {
  @Prompt({
    name: 'compose-prospect-outreach',
    title: 'Compose: Prospect Outreach',
    description: 'Compose a compliant prospect outreach email as a draft',
    parameters: ProspectOutreachSchema,
    _meta: {
      'unique.app/category': 'Compose',
    },
  })
  public composeProspectOutreach({
    recipient,
    clientName,
    valueProp,
    callToAction,
  }: z.infer<typeof ProspectOutreachSchema>) {
    return {
      description: 'Draft a concise, professional outreach email',
      messages: [
        {
          role: 'user' as const,
          content: {
            type: 'text' as const,
            text:
              `Draft an outreach email to ${clientName}. Tone: professional, low-pressure. Include value proposition (${valueProp}), one social proof, and a single CTA (${callToAction}). ` +
              `Create a draft to ${recipient} using create-draft-email.`,
          },
        },
      ],
    };
  }

  @Prompt({
    name: 'compose-meeting-followup',
    title: 'Compose: Meeting Followup',
    description: 'Compose a meeting follow-up email summarizing decisions and next steps',
    parameters: MeetingFollowupSchema,
    _meta: {
      'unique.app/category': 'Compose',
    },
  })
  public composeMeetingFollowup({
    recipient,
    clientName,
    meetingNotes,
    nextSteps,
    dueDates,
  }: z.infer<typeof MeetingFollowupSchema>) {
    const steps = nextSteps;
    const dues = dueDates;
    return {
      description: 'Draft a follow-up email with clear next steps and ownership',
      messages: [
        {
          role: 'user' as const,
          content: {
            type: 'text' as const,
            text:
              `Draft a follow-up to ${clientName} summarizing: ${meetingNotes}. ` +
              `List next steps (${steps})${dues ? ` with due dates (${dues})` : ''}. Create a draft to ${recipient}.`,
          },
        },
      ],
    };
  }

  @Prompt({
    name: 'compose-kyc-aml-request',
    title: 'Compose: KYC/AML Request',
    description: 'Compose a KYC/AML document request email with secure upload instructions',
    parameters: KycAmlSchema,
    _meta: {
      'unique.app/category': 'Compose',
    },
  })
  public composeKycAmlRequest({
    recipient,
    clientName,
    docChecklist,
    securePortalUrl,
    supportContact,
  }: z.infer<typeof KycAmlSchema>) {
    const list = docChecklist;
    return {
      description: 'Draft a KYC/AML document request with compliance tone',
      messages: [
        {
          role: 'user' as const,
          content: {
            type: 'text' as const,
            text:
              `Draft a KYC/AML request to ${clientName} listing: ${list}. ` +
              `Provide upload instructions for ${securePortalUrl} and ${supportContact}. Create draft to ${recipient}.`,
          },
        },
      ],
    };
  }

  @Prompt({
    name: 'compose-rfp-cover',
    title: 'Compose: RFP Cover',
    description: 'Compose a concise RFP cover email',
    parameters: RfpCoverSchema,
    _meta: {
      'unique.app/category': 'Compose',
    },
  })
  public composeRfpCover({
    recipient,
    firmName,
    rfpTitle,
    submissionDeadline,
    differentiators,
  }: z.infer<typeof RfpCoverSchema>) {
    const diffs = differentiators.join(', ');
    return {
      description: 'Draft an RFP cover email with deadline and differentiators',
      messages: [
        {
          role: 'user' as const,
          content: {
            type: 'text' as const,
            text:
              `Draft a cover email for "${rfpTitle}" from ${firmName}. Mention deadline ${submissionDeadline} and differentiators: ${diffs}. ` +
              `Create a draft to ${recipient}.`,
          },
        },
      ],
    };
  }

  @Prompt({
    name: 'compose-investor-update',
    title: 'Compose: Investor Update',
    description: 'Compose an investor monthly update email with disclaimers',
    parameters: InvestorUpdateSchema,
    _meta: {
      'unique.app/category': 'Compose',
    },
  })
  public composeInvestorUpdate({
    recipient,
    fundName,
    period,
    performance,
    drivers,
    risks,
    disclaimers,
  }: z.infer<typeof InvestorUpdateSchema>) {
    const d = drivers;
    const r = risks;
    return {
      description:
        'Draft an investor update with performance, drivers, risks, outlook, and disclaimers',
      messages: [
        {
          role: 'user' as const,
          content: {
            type: 'text' as const,
            text:
              `Draft an investor update for ${fundName} covering ${period}. Include performance (${performance}), key drivers (${d}), notable risks (${r}), outlook, and link to factsheet. ` +
              `Append disclaimers: ${disclaimers}. Create a draft to ${recipient}.`,
          },
        },
      ],
    };
  }

  @Prompt({
    name: 'compose-sensitive-info-request',
    title: 'Compose: Sensitive Info Request',
    description: 'Compose a sensitive information request with compliance language',
    parameters: SensitiveInfoRequestSchema,
    _meta: {
      'unique.app/category': 'Compose',
    },
  })
  public composeSensitiveInfoRequest({
    recipient,
    clientName,
    infoRequested,
    secureMethod,
    disclaimer,
  }: z.infer<typeof SensitiveInfoRequestSchema>) {
    const info = infoRequested;
    return {
      description: 'Draft a sensitive info request that avoids PII in the email body',
      messages: [
        {
          role: 'user' as const,
          content: {
            type: 'text' as const,
            text:
              `Request from ${clientName} the following: ${info}. Instruct to use ${secureMethod}. Avoid including PII in the email body. ` +
              `Include disclaimer: ${disclaimer}. Create draft to ${recipient}.`,
          },
        },
      ],
    };
  }

  @Prompt({
    name: 'compose-introduction',
    title: 'Compose: Introduction',
    description: 'Compose a double-opt introduction email between two parties',
    parameters: IntroductionSchema,
    _meta: {
      'unique.app/category': 'Compose',
    },
  })
  public composeIntroduction({ toA, toB, context, ask }: z.infer<typeof IntroductionSchema>) {
    return {
      description: 'Draft a short and respectful introduction email',
      messages: [
        {
          role: 'user' as const,
          content: {
            type: 'text' as const,
            text: `Draft a double-opt introduction between ${toA} and ${toB}. Context: ${context}. Ask: ${ask}. Create draft.`,
          },
        },
      ],
    };
  }

  @Prompt({
    name: 'compose-auto-ack',
    title: 'Compose: Auto Ack',
    description: 'Compose an acknowledgment reply draft with SLA',
    parameters: AutoAckSchema,
    _meta: {
      'unique.app/category': 'Compose',
    },
  })
  public composeAutoAck({ messageId, recipient, slaHint }: z.infer<typeof AutoAckSchema>) {
    return {
      description: 'Draft a brief acknowledgment confirming receipt and expected response time',
      messages: [
        {
          role: 'user' as const,
          content: {
            type: 'text' as const,
            text:
              `Read ${messageId} (get-mail-message) and draft a brief acknowledgment to ${recipient} confirming receipt and expected response time (${slaHint}). ` +
              `Avoid commitments beyond the SLA. Create draft.`,
          },
        },
      ],
    };
  }

  @Prompt({
    name: 'compose-followup-nudge',
    title: 'Compose: Followup Nudge',
    description: 'Compose a polite, concise follow-up referencing the last exchange',
    parameters: FollowupNudgeSchema,
    _meta: {
      'unique.app/category': 'Compose',
    },
  })
  public composeFollowupNudge({ recipient, threadQuery }: z.infer<typeof FollowupNudgeSchema>) {
    return {
      description: 'Draft a follow-up under 100 words with context',
      messages: [
        {
          role: 'user' as const,
          content: {
            type: 'text' as const,
            text:
              `Find the last exchange for "${threadQuery}" (search-email). Draft a polite follow-up to ${recipient} referencing the last message, ` +
              `asking for a quick update. Keep it under 100 words. Create draft.`,
          },
        },
      ],
    };
  }

  @Prompt({
    name: 'compose-oof',
    title: 'Compose: OOF',
    description: 'Compose an out-of-office reply draft',
    parameters: OutOfOfficeSchema,
    _meta: {
      'unique.app/category': 'Compose',
    },
  })
  public composeOutOfOffice({
    recipient,
    returnDate,
    backupContact,
  }: z.infer<typeof OutOfOfficeSchema>) {
    return {
      description: 'Draft an OOO reply including return date and backup contact',
      messages: [
        {
          role: 'user' as const,
          content: {
            type: 'text' as const,
            text: `Draft a concise OOO reply to ${recipient} including return date ${returnDate} and backup contact ${backupContact}. Create draft.`,
          },
        },
      ],
    };
  }

  @Prompt({
    name: 'compose-trade-confirmation-summary',
    title: 'Compose: Trade Confirmation Summary',
    description: 'Summarize a trade confirmation and draft a clean internal summary',
    parameters: TradeConfirmationSummarySchema,
    _meta: {
      'unique.app/category': 'Compose',
    },
  })
  public composeTradeConfirmationSummary({
    messageId,
    recipient,
  }: z.infer<typeof TradeConfirmationSummarySchema>) {
    return {
      description: 'Extract key trade details and draft an internal summary email',
      messages: [
        {
          role: 'user' as const,
          content: {
            type: 'text' as const,
            text:
              `Extract trade details from ${messageId} (instrument, side, quantity, price, trade date, settle date, broker) using get-mail-message. ` +
              `Draft a clean summary to ${recipient} for internal logging. Create draft.`,
          },
        },
      ],
    };
  }

  @Prompt({
    name: 'compose-compliance-escalation',
    title: 'Compose: Compliance Escalation',
    description: 'Draft an escalation email to compliance with quotes and triage priority',
    parameters: ComplianceEscalationSchema,
    _meta: {
      'unique.app/category': 'Compose',
    },
  })
  public composeComplianceEscalation({
    messageId,
    recipient,
    issueSummary,
  }: z.infer<typeof ComplianceEscalationSchema>) {
    return {
      description: 'Summarize the issue and include key quotes, propose triage priority',
      messages: [
        {
          role: 'user' as const,
          content: {
            type: 'text' as const,
            text:
              `Draft an escalation email to ${recipient} summarizing: ${issueSummary}. Include key quotes from ${messageId} (get-mail-message) ` +
              `and propose a triage priority. Create draft.`,
          },
        },
      ],
    };
  }

  @Prompt({
    name: 'compose-generic-draft',
    title: 'Compose: Generic Draft',
    description: 'Draft an email to a recipient about a subject',
    parameters: GenericDraftSchema,
    _meta: {
      'unique.app/category': 'Compose',
    },
  })
  public composeGenericDraft({ recipient, subject }: z.infer<typeof GenericDraftSchema>) {
    return {
      description: 'Draft a concise, professional email skeleton with the given subject',
      messages: [
        {
          role: 'user' as const,
          content: {
            type: 'text' as const,
            text:
              `Create a professional email draft to ${recipient} with subject "${subject}". ` +
              `Keep it concise and clearly state purpose and optional next step. Create draft.`,
          },
        },
      ],
    };
  }
}
