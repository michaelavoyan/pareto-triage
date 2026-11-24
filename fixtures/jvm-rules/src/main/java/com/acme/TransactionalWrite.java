package com.acme;

import android.database.sqlite.SQLiteDatabase;

/** The same two writes inside a transaction: correct, so it must be silent. */
public final class TransactionalWrite {
    public void transfer(SQLiteDatabase db, long from, long to, long amount) {
        db.beginTransaction();
        try {
            db.execSQL("UPDATE accounts SET balance = balance - " + amount + " WHERE id = " + from);
            db.update("accounts", null, "id = ?", new String[]{String.valueOf(to)});
            db.setTransactionSuccessful();
        } finally {
            db.endTransaction();
        }
    }

    /** One write only: no atomicity question to raise. */
    public void rename(SQLiteDatabase db, long id, String name) {
        db.update("accounts", null, "id = ?", new String[]{String.valueOf(id)});
    }
}
