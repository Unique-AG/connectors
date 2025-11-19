import pretty from 'pino-pretty';

const development = (opts: pretty.PrettyOptions) =>
  pretty({
    ...opts,
    translateTime: 'SYS:yyyy-mm-dd HH:MM:ss.l',
    ignore: 'trace_flags,hostname,pid',
    customPrettifiers: {
      caller: (caller, _key, _log, { colors }) =>
        `${colors.bold(colors.yellowBright(caller.toString()))}`,
    },
  });

export default development;
