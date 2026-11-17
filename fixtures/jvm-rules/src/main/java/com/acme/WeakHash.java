package com.acme;

import java.security.MessageDigest;

public final class WeakHash {
    public MessageDigest digest() throws Exception {
        return MessageDigest.getInstance("MD5");
    }
}
