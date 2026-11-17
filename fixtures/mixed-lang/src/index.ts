import express from 'express'

const app = express()

export function runScript(req: any) {
  return eval(req.query.code)
}

app.get('/run', runScript)

export { app }
