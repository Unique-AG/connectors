import { BadRequestException, Controller, Get, Logger, Query, Res } from '@nestjs/common';
import { ApiTags } from '@nestjs/swagger';
import { Response } from 'express';
import { decompressData } from './decompress-data';

@ApiTags('Scoped')
@Controller({ path: 'scoped' })
export class ScopedAPIController {
  private readonly logger = new Logger(this.constructor.name);

  @Get('decompress-html-data')
  public async mirrorContent(@Query('data') data: string, @Res() res: Response) {
    // Validate input parameter
    if (!data) {
      throw new BadRequestException('Data query parameter is required');
    }

    try {
      const unzippedData = await decompressData(data);

      // Set Content-Type header to text/html for proper browser rendering
      res.setHeader('Content-Type', 'text/html; charset=utf-8');

      return res.send(unzippedData);
    } catch (error) {
      // Log the error for debugging
      this.logger.error({ msg: 'Failed to mirror data', error });

      // Re-throw BadRequestException as-is, wrap others
      if (error instanceof BadRequestException) {
        throw error;
      }

      throw new BadRequestException('Failed to process data: invalid or malformed input');
    }
  }
}
