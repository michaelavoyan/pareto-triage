package com.acme.service;

import com.acme.model.Money;

public class PricingService {

    public long price(String sku) {
        return Money.cents(sku);
    }

    public String describe() {
        return "pricing";
    }
}
