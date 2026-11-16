import express from 'express'
import { chargeCard } from './billing'

const app = express()
const router = express.Router()

app.post('/webhooks/stripe', async (req, res) => {
  const event = req.body
  await chargeCard(event.amount)
  res.json({ ok: true })
})

router.get('/health', (_req, res) => res.json({ ok: true }))

export { app, router }
