package com.acme;

import android.database.sqlite.SQLiteDatabase;

/** Two writes, no transaction: a crash between them leaves a torn state. */
public final class NonAtomicWrite {
    public void transfer(SQLiteDatabase db, long from, long to, long amount) {
        db.execSQL("UPDATE accounts SET balance = balance - " + amount + " WHERE id = " + from);
        db.update("accounts", null, "id = ?", new String[]{String.valueOf(to)});
    }
}
