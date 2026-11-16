import express from 'express'
import { boot } from './index'

const app = express()

app.use('/api', rateLimit)

app.get('/health', (_req, res) => res.json({ ok: true }))

export { app, boot }
