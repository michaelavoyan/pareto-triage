package com.acme;

import okhttp3.OkHttpClient;

/** A client built without any timeout: the absence is visible in the chain. */
public final class HttpNoTimeout {
    public OkHttpClient build() {
        return new OkHttpClient.Builder()
                .retryOnConnectionFailure(false)
                .build();
    }
}
