export function runScript(source: string) {
  return eval(source)
}

export const agent = { rejectUnauthorized: false }
