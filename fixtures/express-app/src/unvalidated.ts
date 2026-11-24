import express from 'express'
import { db } from './db'

const router = express.Router()

router.post('/jobs/:id', (req, res) => {
  // Fires: the body value reaches the query unvalidated.
  db.query("SELECT * FROM jobs WHERE id = " + req.body.id)

  // Fires: the route parameter reaches the statement.
  db.prepare("DELETE FROM jobs WHERE id = ?").run(req.params.id)

  // Fires through an alias: the taint follows the name to the sink.
  const limit = req.query.limit
  db.run("SELECT * FROM jobs LIMIT " + limit)

  // Silent: the value is parsed to a number before the sink.
  db.query("SELECT * FROM jobs LIMIT " + Number(req.query.limit))

  // Silent: parseInt is a parse, not a pass-through.
  db.prepare("DELETE FROM jobs WHERE id = ?").run(parseInt(req.params.id, 10))

  res.json({ ok: true })
})

export { router }
