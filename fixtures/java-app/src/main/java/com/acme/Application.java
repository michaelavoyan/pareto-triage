package com.acme;

import com.acme.api.OrdersController;

public class Application {

    public static void main(String[] args) {
        OrdersController controller = new OrdersController(null);
        System.out.println(controller.listOrders());
    }
}
