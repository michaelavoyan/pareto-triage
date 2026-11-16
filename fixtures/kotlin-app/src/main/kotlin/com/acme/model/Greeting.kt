package com.acme.model

data class Greeting(val name: String) {
    val text: String
        get() = "hello " + name
}
