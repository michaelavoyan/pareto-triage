package com.acme

import java.security.NoSuchAlgorithmException

class NameCollisionTables {
  fun collisionKey(names: List<String>): String {
    if (names.isEmpty()) {
      return ""
    }

    return try {
      names.sorted().joinToString(separator = "\u0000")
    } catch (e: NoSuchAlgorithmException) {
      ""
    }
  }
}
