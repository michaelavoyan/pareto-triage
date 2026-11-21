package com.acme;

import android.util.Log;

/** Logging then returning a distinct error value is not a fall-through. */
public final class CatchReturnsError {
    private static final String TAG = "CatchReturnsError";

    public int parse(String raw) {
        try {
            return Integer.parseInt(raw);
        } catch (NumberFormatException e) {
            Log.e(TAG, "unreadable value", e);
            return -1;
        }
    }
}
