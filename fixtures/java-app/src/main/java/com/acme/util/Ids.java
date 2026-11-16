package com.acme.util;

import java.util.UUID;

public class Ids {

    public String next() {
        return UUID.randomUUID().toString();
    }
}
