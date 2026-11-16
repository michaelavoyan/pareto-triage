package com.acme.api;

import com.acme.service.OrderService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;

import java.util.List;

public class OrdersController {

    private final OrderService service;

    public OrdersController(OrderService service) {
        this.service = service;
    }

    @GetMapping("/orders")
    public List<String> listOrders() {
        return service.listOrders();
    }

    @PostMapping("/orders")
    public String createOrder(String sku) {
        return service.create(sku);
    }
}
