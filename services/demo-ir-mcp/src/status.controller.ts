import { Controller, Get, Header } from '@nestjs/common';
import { DemoRepository } from './data/demo.repository';

@Controller()
export class StatusController {
  public constructor(private readonly repository: DemoRepository) {}

  @Get('probe')
  public getProbe() {
    return {
      status: 'ok',
      database: 'ready',
      relationships: this.repository.list('relationships').length,
    };
  }

  @Get('manifest')
  @Header('Cache-Control', 'no-store')
  public getManifest() {
    return {
      name: '@unique-ag/demo-ir-mcp',
      version: '0.1.0',
      type: 'mcp-server',
      authentication: 'none',
      endpoints: {
        frontend: '/',
        api: '/api',
        mcp: '/mcp',
        probe: '/probe',
      },
      snapshotDate: this.repository.snapshotDate,
      disclaimer: 'Public dummy data for demonstration only.',
    };
  }
}
