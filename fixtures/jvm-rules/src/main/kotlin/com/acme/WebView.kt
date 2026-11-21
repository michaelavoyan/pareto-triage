package com.acme

import android.content.Context

fun getLogText(context: Context): String {
  return try {
    context.assets.open("log.txt").bufferedReader().use { it.readText() }
  } catch (e: Exception) {
    "Error loading file: ${e.message}"
  }
}
