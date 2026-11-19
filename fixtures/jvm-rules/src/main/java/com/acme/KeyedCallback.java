package com.acme;

import java.util.concurrent.Executor;

/** A keyed executor's execute() dispatches a task; it is not a SQL statement. */
public final class KeyedCallback {
    public void submit(Executor keyedExecutor, ReplyInfo info) {
        keyedExecutor.execute("Call::" + info.getRecipientId(), () -> {
            info.deliver();
        });
    }

    interface ReplyInfo {
        String getRecipientId();

        void deliver();
    }
}
