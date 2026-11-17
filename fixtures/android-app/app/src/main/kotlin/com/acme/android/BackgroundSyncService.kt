package com.acme.android

/** Indirect background component: BackgroundSyncService -> BaseSyncService ->
 *  Service. */
class BackgroundSyncService : BaseSyncService() {
    fun sync() {
        // Drains the outbox.
    }
}
