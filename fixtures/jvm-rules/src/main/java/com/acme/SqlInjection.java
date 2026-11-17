package com.acme;

import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.Statement;

public final class SqlInjection {
    public ResultSet find(Connection connection, String id) throws Exception {
        Statement statement = connection.createStatement();
        return statement.executeQuery("SELECT * FROM orders WHERE id = '" + id + "'");
    }
}
