import { Activities, Activity } from '@unique-ag/temporal';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { components } from '@qdrant/js-client-rest/dist/types/openapi/generated_schema';
import dayjs from 'dayjs';
import { and, eq } from 'drizzle-orm';
import { addressToString, DRIZZLE, DrizzleDatabase, emails as emailsTable } from '../../../drizzle';
import { QdrantService } from '../../../qdrant/qdrant.service';

export interface IIndexActivity {
  index(payload: IndexPayload): Promise<void>;
}

interface IndexPayload {
  userProfileId: string;
  emailId: string;
}

@Injectable()
@Activities()
export class IndexActivity {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly qdrantService: QdrantService,
  ) {}

  @Activity()
  public async index({ userProfileId, emailId }: IndexPayload) {
    const email = await this.db.query.emails.findFirst({
      where: and(eq(emailsTable.id, emailId), eq(emailsTable.userProfileId, userProfileId)),
      with: {
        points: true,
      },
    });

    if (!email) {
      this.logger.warn('Email not found, skipping index');
      return;
    }

    if (email.points.length === 0) {
      this.logger.warn('Email has no vectors, skipping index');
      return;
    }

    await this.qdrantService.ensureCollection({
      name: 'emails',
      vectors: {
        content: {
          size: 1024,
          distance: 'Cosine',
        },
      },
    });

    const points: components['schemas']['PointStruct'][] = [];
    const chunkTotal = email.points.filter((p) => p.pointType === 'chunk').length;
    const metadata = {
      user_profile_id: userProfileId,
      email_id: emailId,
      subject: email.subject,
      language: email.language,
      attachment_count: email.attachmentCount,
      attachments: email.attachments?.map((a) => a.filename).join(','),
      tags: email.tags?.join(','),
      from: addressToString(email.from),
      to: email.to?.map(addressToString).join(','),
      cc: email.cc?.map(addressToString).join(','),
      bcc: email.bcc?.map(addressToString).join(','),
      sent_at: dayjs(email.sentAt).unix(),
      received_at: dayjs(email.receivedAt).unix(),
    };

    for (const point of email.points) {
      const payload =
        point.pointType === 'chunk'
          ? {
              ...metadata,
              point_type: 'chunk',
              chunk_index: point.index,
              chunk_total: chunkTotal,
            }
          : {
              ...metadata,
              point_type: point.pointType,
            };

      const pointStruct = {
        id: point.qdrantId.toString(),
        vector: {
          content: point.vector,
        },
        payload,
      };
      points.push(pointStruct);
    }

    await this.qdrantService.upsert('emails', points);
  }
}
