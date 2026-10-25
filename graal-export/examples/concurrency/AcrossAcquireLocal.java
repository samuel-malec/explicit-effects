package concurrency;

/**
 * An acquire between a store and a load: `poll` reads a volatile field, which
 * makes what another thread wrote before setting the flag visible here. But
 * the counter is allocated in `main` and never stored where another thread
 * could reach it, so no other thread writes its value: the load may take the 5.
 * Telling that apart needs a thread-escape analysis.
 */
public class AcrossAcquireLocal {

    static class Counter { int value; }

    static volatile boolean ready;

    static boolean poll(int n) {
        return n > 0 ? poll(n - 1) : ready;
    }

    static int demo(Counter counter, int n) {
        counter.value = 5;
        poll(n);
        return counter.value;
    }

    static int sink;

    public static void main(String[] args) {
        sink = demo(new Counter(), args.length);
    }
}
