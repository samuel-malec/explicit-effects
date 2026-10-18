package concurrency;

/**
 * A lock on an object no other thread can reach: `main` allocates the tally and
 * passes it only to `demo`. No other thread can take its monitor, so taking it
 * synchronizes with nothing, and the load may take the 5 even though the
 * counter is in a static field that other threads can reach. This is the case
 * lock elision needs. Today the call takes every token, and the load stays.
 */
public class AcrossLocalMonitor {

    static class Counter { int value; }

    static class Tally {
        int count;

        // Recursive, so that Graal can't inline it before the analysis.
        synchronized void add(int n) {
            if (n > 0) {
                add(n - 1);
            } else {
                count++;
            }
        }
    }

    static Counter shared = new Counter();

    static int demo(Tally tally, int n) {
        Counter counter = shared;
        counter.value = 5;
        tally.add(n);
        return counter.value;
    }

    static int sink;

    public static void main(String[] args) {
        sink = demo(new Tally(), args.length);
    }
}
