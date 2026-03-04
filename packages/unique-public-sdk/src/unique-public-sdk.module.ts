import { type DynamicModule, Module, type Provider } from '@nestjs/common';
import { ZodConfigurableModuleBuilder } from '@proventuslabs/nestjs-zod';
import { fullJitter, upto } from '@proventuslabs/retry-strategies';
import {
  type FetchFn,
  pipeline,
  withBaseUrl,
  withHeaders,
  withResponseError,
  withRetryAfter,
  withRetryStatus,
} from '@qfetch/qfetch';
import { UniqueContentService } from './services/unique-content.service';
import { UniqueScopeService } from './services/unique-scope.service';
import { UniqueUserService } from './services/unique-user.service';
import {
  UNIQUE_PUBLIC_FETCH,
  UNIQUE_PUBLIC_SDK_OPTIONS,
  USER_IDENTITY_RESOLVER,
} from './unique-public-sdk.consts';
import {
  type UniquePublicSdkOptions,
  UniquePublicSdkOptionsSchema,
} from './unique-public-sdk.options';

const { ConfigurableModuleClass, OPTIONS_INPUT_TYPE, ASYNC_OPTIONS_INPUT_TYPE } =
  new ZodConfigurableModuleBuilder(UniquePublicSdkOptionsSchema, {
    optionsInjectionToken: UNIQUE_PUBLIC_SDK_OPTIONS,
  })
    .setClassMethodName('forRoot')
    .build();

function createProviders(): Provider[] {
  return [
    {
      provide: UNIQUE_PUBLIC_FETCH,
      inject: [UNIQUE_PUBLIC_SDK_OPTIONS],
      useFactory(opts: UniquePublicSdkOptions): FetchFn {
        return pipeline(
          withBaseUrl(opts.apiBaseUrl),
          withHeaders({
            'x-api-version': opts.apiVersion,
            ...opts.serviceHeaders,
          }),
          withRetryStatus({
            strategy: () =>
              upto(
                opts.retry.maxAttempts,
                fullJitter(opts.retry.baseDelayMs, opts.retry.maxDelayMs),
              ),
          }),
          withRetryAfter({
            strategy: () =>
              upto(
                opts.retry.maxAttempts,
                fullJitter(opts.retry.baseDelayMs, opts.retry.maxDelayMs),
              ),
            maxServerDelay: opts.retry.maxDelayMs * 2,
          }),
          withResponseError(),
        )(fetch);
      },
    },
    {
      provide: USER_IDENTITY_RESOLVER,
      inject: [UNIQUE_PUBLIC_SDK_OPTIONS],
      useFactory: (opts: UniquePublicSdkOptions) => opts.userIdentityResolver ?? null,
    },
    UniqueContentService,
    UniqueScopeService,
    UniqueUserService,
  ];
}

const EXPORTS = [
  UNIQUE_PUBLIC_FETCH,
  USER_IDENTITY_RESOLVER,
  UniqueContentService,
  UniqueScopeService,
  UniqueUserService,
];

@Module({})
class UniquePublicSdkInner extends ConfigurableModuleClass {}

export const UniquePublicSdkModule = {
  forRoot: (options: typeof OPTIONS_INPUT_TYPE): DynamicModule => {
    const dynamicModule = UniquePublicSdkInner.forRoot(options);
    return {
      ...dynamicModule,
      global: true,
      providers: [...(dynamicModule.providers ?? []), ...createProviders()],
      exports: EXPORTS,
    };
  },

  forRootAsync: (options: typeof ASYNC_OPTIONS_INPUT_TYPE): DynamicModule => {
    const dynamicModule = UniquePublicSdkInner.forRootAsync(options);
    return {
      ...dynamicModule,
      global: true,
      providers: [...(dynamicModule.providers ?? []), ...createProviders()],
      exports: EXPORTS,
    };
  },
};
