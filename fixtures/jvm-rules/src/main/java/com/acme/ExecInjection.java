package com.acme;

public final class ExecInjection {
    public Process run(String path) throws java.io.IOException {
        return Runtime.getRuntime().exec("convert " + path);
    }
}
