package com.acme;

import java.util.concurrent.TimeUnit;

import okhttp3.OkHttpClient;

/** The same chain with a call timeout must stay quiet. */
public final class HttpTimeout {
    public OkHttpClient build() {
        return new OkHttpClient.Builder()
                .callTimeout(30, TimeUnit.SECONDS)
                .build();
    }
}
