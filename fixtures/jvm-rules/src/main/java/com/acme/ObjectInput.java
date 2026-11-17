package com.acme;

import java.io.InputStream;
import java.io.ObjectInputStream;

public final class ObjectInput {
    public Object read(InputStream stream) throws Exception {
        ObjectInputStream in = new ObjectInputStream(stream);
        return in.readObject();
    }
}
