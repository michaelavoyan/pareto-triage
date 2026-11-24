import knex from 'knex'

// The receiver is not a database name, but the file imports a SQL driver.
export function expensiveJobs(score: number) {
  return knex.raw(`SELECT * FROM scores WHERE score > ${score}`)
}
