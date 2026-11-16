package com.acme.service

import com.acme.legacy.LegacyStore
import com.acme.model.Greeting

class GreetingService(private val store: LegacyStore) {

    fun greet(name: String): String {
        val greeting = Greeting(name)
        store.save(greeting.text)
        return greeting.text
    }
}
