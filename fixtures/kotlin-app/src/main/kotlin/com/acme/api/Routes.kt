package com.acme.api

import com.acme.legacy.LegacyStore
import com.acme.service.GreetingService
import com.acme.service.clock
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PostMapping

class Routes(private val service: GreetingService) {

    @GetMapping("/greet")
    fun greet(name: String): String {
        return service.greet(name) + " at " + clock()
    }

    @PostMapping("/greet")
    fun createGreeting(name: String): String = service.greet(name)
}

fun main(args: Array<String>) {
    val store = LegacyStore()
    val routes = Routes(GreetingService(store))
    println(routes.greet(args.firstOrNull() ?: "world"))
}
