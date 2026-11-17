package com.acme;

import java.io.ObjectOutputStream;
import java.io.OutputStream;
import java.security.MessageDigest;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.Statement;

/** Every rule has a counterpart here that must stay quiet. */
public final class SafeCounterparts {
    public static void main(String[] args) {
        // entrypoint, so the fixture passes the gate
    }

    public Process run() throws java.io.IOException {
        return Runtime.getRuntime().exec("ls");
    }

    public Process build() throws java.io.IOException {
        return new ProcessBuilder("ls").start();
    }

    public ResultSet find(Connection connection) throws Exception {
        Statement statement = connection.createStatement();
        return statement.executeQuery("SELECT * FROM orders WHERE id = ?");
    }

    public int parse(String raw) {
        try {
            return Integer.parseInt(raw);
        } catch (NumberFormatException e) {
            return 0;
        }
    }

    public MessageDigest digest() throws Exception {
        return MessageDigest.getInstance("SHA-256");
    }

    public void write(OutputStream stream) throws Exception {
        ObjectOutputStream out = new ObjectOutputStream(stream);
        out.flush();
    }
}
