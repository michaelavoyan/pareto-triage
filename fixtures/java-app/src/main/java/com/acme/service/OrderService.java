package com.acme.service;

import com.acme.model.Customer;
import com.acme.model.Order;
import com.acme.util.Ids;

import java.util.List;

public class OrderService {

    private final PricingService pricing = new PricingService();
    private final Ids ids = new Ids();

    public String create(String sku) {
        Order order = new Order(sku, pricing.price(sku), ids.next());
        return order.describe();
    }

    public List<String> listOrders() {
        Customer customer = new Customer();
        customer.name = "acme";
        return List.of(customer.name, pricing.describe());
    }
}
