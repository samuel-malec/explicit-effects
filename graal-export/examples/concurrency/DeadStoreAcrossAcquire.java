package concurrency;

/**
 * A store, an acquire, and a store that overwrites the first. An acquire can
 * show this thread other threads' writes, but shows them none of this thread's,
 * so no other thread can read the 1: the Java memory model lets the first store
 * go. The rules keep it today: they count an acquire as a read, which is safe.
 */
public class DeadStoreAcrossAcquire {

    static class Counter { int value; }

    static volatile boolean ready;

    static boolean demo(Counter counter) {
        counter.value = 1;
        boolean seen = ready;
        counter.value = 2;
        return seen;
    }

    static boolean sink;

    public static void main(String[] args) {
        sink = demo(new Counter());
    }
}
