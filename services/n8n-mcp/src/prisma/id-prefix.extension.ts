import { Prisma } from '@generated/prisma';
import { BaseDMMF } from '@generated/prisma/runtime/library';
import { typeid } from 'typeid-js';

function _getPrefixFromModel(
  model: BaseDMMF['datamodel']['models'][number] | undefined,
): string | undefined {
  const prefixAnnotationRegex = /@idPrefix\((?<prefix>.*)\)/;
  return model?.documentation?.match(prefixAnnotationRegex)?.groups?.prefix;
}

export const createIdPrefixExtension = (prefixMap: Record<Prisma.DMMF.Model['name'], string>) =>
  Prisma.defineExtension({
    name: 'idPrefix',
    query: {
      $allModels: {
        async $allOperations({ operation, model, args, query }) {
          const idPrefix = prefixMap[model];

          switch (operation) {
            case 'create': {
              return query({
                ...args,
                data: {
                  ...args.data,
                  id:
                    args.data.id || (idPrefix ? typeid(idPrefix).toString() : typeid().toString()),
                },
              });
            }

            case 'createMany': {
              if (!Array.isArray(args.data)) return query(args);

              return query({
                ...args,
                data: args.data.map((item: Record<string, unknown>) => ({
                  ...item,
                  id: item.id || (idPrefix ? typeid(idPrefix).toString() : typeid().toString()),
                })),
              });
            }

            case 'upsert': {
              return query({
                ...args,
                create: {
                  ...args.create,
                  id:
                    args.create.id ||
                    (idPrefix ? typeid(idPrefix).toString() : typeid().toString()),
                },
              });
            }

            default:
              return query(args);
          }
        },
      },
    },
  });
