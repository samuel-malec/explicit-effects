package concurrency;

/**
 * Volatile accesses to a field of an object no other thread can reach: `main` allocates the gauge and
 * passes it only to `demo`. A volatile access orders this thread with the others that access the same
 * field, and there are none, so the accesses can be ordinary ones.
 */
public class VolatileOnLocal {

    static class Gauge {
        volatile int level;
    }

    // Recursive, so that Graal can't inline it before the analysis.
    static int fill(Gauge gauge, int n) {
        if (n > 0) {
            return fill(gauge, n - 1);
        }
        gauge.level = gauge.level + 1;
        return gauge.level;
    }

    static int sink;

    public static void main(String[] args) {
        sink = fill(new Gauge(), args.length);
    }
}
