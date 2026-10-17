package objects;

/**
 * Control for ForwardPastOtherObject: main also passes one counter twice, so the
 * same access may touch either object, the analysis puts both in one set, and the
 * load must read the 2 when both references point to one object.
 */
public class ForwardPastMaybeAlias {

    static class Counter { int value; }

    static int demo(Counter counter, Counter other) {
        counter.value = 1;
        other.value = 2;
        return counter.value;
    }

    static int sink;

    public static void main(String[] args) {
        Counter shared = new Counter();
        sink = demo(new Counter(), new Counter()) + demo(shared, shared);
    }
}
