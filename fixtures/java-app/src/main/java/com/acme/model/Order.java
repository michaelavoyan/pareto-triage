package com.acme.model;

public class Order {

    private final String sku;
    private final long cents;
    private final String id;

    public Order(String sku, long cents, String id) {
        this.sku = sku;
        this.cents = cents;
        this.id = id;
    }

    public String describe() {
        return id + " " + sku + " " + cents;
    }
}
