package com.acme.android;

import android.os.Bundle;

import androidx.appcompat.app.AppCompatActivity;

import com.acme.android.data.OrderStore;

public class MainActivity extends AppCompatActivity {
    private final OrderStore store = new OrderStore();

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        store.load();
    }
}
