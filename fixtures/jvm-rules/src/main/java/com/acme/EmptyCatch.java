package com.acme;

public final class EmptyCatch {
    public int parse(String raw) {
        try {
            return Integer.parseInt(raw);
        } catch (NumberFormatException e) {
            // an unreadable value counts as zero
        }
        return 0;
    }
}
