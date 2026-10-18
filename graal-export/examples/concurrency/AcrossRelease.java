package concurrency;

/**
 * A release between a store and a load: `publish` writes a volatile field. A
 * release makes this thread's earlier writes visible to a thread that later
 * reads the flag, but lets no other thread's write in. So in a program free of
 * data races the load may take the 5, whatever the object. Today every
 * synchronization makes its method opaque: the call takes every token, and the
 * load stays.
 */
public class AcrossRelease {

    static class Counter { int value; }

    static volatile boolean ready;

    // Recursive, so that Graal can't inline it before the analysis.
    static void publish(int n) {
        if (n > 0) {
            publish(n - 1);
        } else {
            ready = true;
        }
    }

    static int demo(Counter counter, int n) {
        counter.value = 5;
        publish(n);
        return counter.value;
    }

    static int sink;

    public static void main(String[] args) {
        sink = demo(new Counter(), args.length);
    }
}
