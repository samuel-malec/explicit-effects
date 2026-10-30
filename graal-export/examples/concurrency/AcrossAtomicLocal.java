package concurrency;

/**
 * An atomic update between a store and a load: `ticket` increments a shared
 * AtomicInteger, a compare-and-swap.
 * The counter is allocated in `main` and no other thread can reach it, so the
 * load may take the 5. 
 */
public class AcrossAtomicLocal {

    static class Counter { int value; }

    static final java.util.concurrent.atomic.AtomicInteger TICKETS = new java.util.concurrent.atomic.AtomicInteger();

    static int ticket(int n) {
        return n > 0 ? ticket(n - 1) : TICKETS.incrementAndGet();
    }

    static int demo(Counter counter, int n) {
        counter.value = 5;
        ticket(n);
        return counter.value;
    }

    static int sink;

    public static void main(String[] args) {
        sink = demo(new Counter(), args.length);
    }
}
