package com.acme

import android.database.sqlite.SQLiteDatabase

class SqlTemplate {
  fun find(db: SQLiteDatabase, id: String) =
    db.query("SELECT * FROM orders WHERE id = '$id'")

  fun findBound(db: SQLiteDatabase, id: String) =
    db.query("SELECT * FROM orders WHERE id = ?", arrayOf(id))
}
