package concurrency;

/**
 * The same volatile accesses to a field of an object that another thread reaches: `main` hands the
 * gauge to a thread, so the accesses must stay volatile. The control for VolatileOnLocal.
 */
public class VolatileOnShared {

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

    public static void main(String[] args) throws InterruptedException {
        Gauge gauge = new Gauge();
        Thread reader = new Thread(() -> sink = gauge.level);
        reader.start();
        sink = fill(gauge, args.length);
        reader.join();
    }
}
