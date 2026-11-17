package com.acme.android

import android.content.Context
import androidx.work.Worker
import androidx.work.WorkerParameters

class UploadWorker(context: Context, params: WorkerParameters) :
    Worker(context, params) {

    override fun doWork(): Result {
        return Result.success()
    }
}
