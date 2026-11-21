package com.acme;

import android.util.Log;

/** Logging before a throw keeps the failure visible to the caller. */
public final class LogThenThrow {
    private static final String TAG = "LogThenThrow";

    public int parse(String raw) {
        try {
            return Integer.parseInt(raw);
        } catch (NumberFormatException e) {
            Log.e(TAG, "unreadable value", e);
            throw new IllegalArgumentException("bad value", e);
        }
    }
}
