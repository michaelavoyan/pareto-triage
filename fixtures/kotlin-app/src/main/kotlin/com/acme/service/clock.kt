package com.acme.service

import java.time.Instant

fun clock(): Long = Instant.now().toEpochMilli()
