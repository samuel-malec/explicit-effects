package objects;

/**
 * Control for DeadStorePastOtherObject: main also passes one counter twice, so the
 * load between may read the 1, and the store stays.
 */
public class DeadStoreMaybeAlias {

    static class Counter { int value; int other; }

    static int demo(Counter counter, Counter other) {
        int seen = other.other;
        counter.value = 1;
        seen += other.value;
        counter.value = 2;
        return seen;
    }

    static int sink;

    public static void main(String[] args) {
        Counter shared = new Counter();
        sink = demo(new Counter(), new Counter()) + demo(shared, shared);
    }
}
