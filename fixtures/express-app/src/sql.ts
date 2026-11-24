import { openDb } from './db'

const db = openDb()

// A withdrawn SQL rule would have needed to reject these shapes; they stay
// here so the boundary is documented and asserted. No rule fires on this file:
// the values are passed separately, the text is a placeholder string, and the
// receiver is not a database.

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
