package com.acme

import android.content.Context
import android.content.pm.PackageManager

class LogSectionSystemInfo {
  private fun getAppInfo(context: Context): String {
    return try {
      val packageManager = context.packageManager
      val appLabel = packageManager.getApplicationLabel(
        packageManager.getApplicationInfo(context.packageName, 0))
      "$appLabel ${packageManager.getPackageInfo(context.packageName, 0).versionName}"
    } catch (_: PackageManager.NameNotFoundException) {
      "Unknown"
    }
  }
}
