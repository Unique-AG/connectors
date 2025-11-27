import { Activities, Activity } from '@unique-ag/temporal';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import {
  DRIZZLE,
  DrizzleDatabase,
  Point,
  PointInput,
  points as pointsTable,
} from '../../../drizzle';

export interface ISavePointsActivity {
  savePoints(payload: SavePointsPayload): Promise<Point[]>;
}

export interface SavePointsPayload {
  userProfileId: string;
  emailId: string;
  points: PointInput[];
}

@Injectable()
@Activities()
export class SavePointsActivity {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(@Inject(DRIZZLE) private readonly db: DrizzleDatabase) {}

  @Activity()
  public async savePoints(payload: SavePointsPayload): Promise<Point[]> {
    const { userProfileId, emailId, points } = payload;

    const densePoints = points.filter((p) => p.vector && p.vector.length > 0);
    const sparsePoints = points.filter((p) => p.sparseVector && p.sparseVector.indices.length > 0);

    const mergedPoints = densePoints.map((densePoint) => {
      const matchingSparsePoint = sparsePoints.find(
        (sp) => sp.pointType === densePoint.pointType && sp.index === densePoint.index
      );
      return {
        ...densePoint,
        sparseVector: matchingSparsePoint?.sparseVector ?? densePoint.sparseVector,
      };
    });

    this.logger.debug({
      msg: 'Saving points',
      userProfileId,
      emailId,
      points: mergedPoints.length,
    });

    await this.db.delete(pointsTable).where(eq(pointsTable.emailId, emailId));

    return this.db.insert(pointsTable).values(mergedPoints).returning();
  }
}
