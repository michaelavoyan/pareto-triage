package com.acme;

/** A fixed command plus a compile-time constant is not injection. */
public final class ConstantExec {
    private static final String FILTER_SPEC = "priority:I";

    public Process dump() throws java.io.IOException {
        return Runtime.getRuntime().exec("logcat -d " + FILTER_SPEC);
    }
}
