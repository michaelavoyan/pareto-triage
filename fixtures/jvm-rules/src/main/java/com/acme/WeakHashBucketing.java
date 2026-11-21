package com.acme;

import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.List;

/** MD5 as an internal bucketing key: no integrity role, still a weak hash. */
public final class WeakHashBucketing {
    public String bucket(List<String> names) throws NoSuchAlgorithmException {
        MessageDigest digest = MessageDigest.getInstance("MD5");
        for (String name : names) {
            digest.update(name.getBytes());
        }
        return bytesToHex(digest.digest());
    }

    private static String bytesToHex(byte[] bytes) {
        StringBuilder out = new StringBuilder(bytes.length * 2);
        for (byte b : bytes) {
            out.append(String.format("%02x", b));
        }
        return out.toString();
    }
}
