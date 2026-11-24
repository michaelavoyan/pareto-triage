import { openDb } from './db'

const db = openDb()

export function findJob(id: string) {
  return db.query(`SELECT * FROM jobs WHERE id = '${id}'`)
}

export function deleteJob(id: string) {
  return db.execute(`DELETE FROM jobs WHERE id = '${id}'`)
}

// The values are passed separately, so the text is fixed.
export function findJobBound(id: string) {
  return db.query(`SELECT * FROM jobs WHERE id = ?`, [id])
}

export function findJobPlaceholder(id: string) {
  return db.query('SELECT * FROM jobs WHERE id = ?', [id])
}

// A GraphQL client is not a database, and this file imports no SQL driver.
export function searchApi(term: string) {
  return api.query(`query { job(term: "${term}") { id } }`)
}
