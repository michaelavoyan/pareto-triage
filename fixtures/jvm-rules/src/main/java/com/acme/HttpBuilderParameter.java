package com.acme;

import okhttp3.OkHttpClient;

/** The builder comes from the caller, so this expression proves no absence. */
public final class HttpBuilderParameter {
    public OkHttpClient finish(OkHttpClient.Builder builder) {
        return builder.build();
    }
}
