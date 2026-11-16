package com.acme.model;

public final class Money {

    private Money() {
    }

    public static long cents(String sku) {
        return sku.length() * 10L;
    }
}
