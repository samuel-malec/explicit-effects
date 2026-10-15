package objects;

/**
 * The load between the stores reads another object: with object partitions it takes
 * another token, so the first store's token goes straight to the overwrite, and the
 * store is dead. Reading other.other first checks other for null before the stores.
 */
public class DeadStorePastOtherObject {

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
        sink = demo(new Counter(), new Counter());
    }
}
