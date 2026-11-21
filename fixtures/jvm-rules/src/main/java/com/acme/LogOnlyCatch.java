package com.acme;

import android.util.Log;

/** The failure is logged, then execution continues as if the parse succeeded. */
public final class LogOnlyCatch {
    private static final String TAG = "LogOnlyCatch";

    public int parse(String raw) {
        try {
            return Integer.parseInt(raw);
        } catch (NumberFormatException e) {
            Log.e(TAG, "unreadable value", e);
        }
        return 0;
    }
}
