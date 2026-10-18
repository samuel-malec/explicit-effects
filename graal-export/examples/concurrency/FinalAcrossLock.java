package concurrency;

/**
 * A final field read on both sides of a lock. A final field keeps the value
 * its constructor gave it, and every thread that sees the object sees that
 * value, so the second load may take the first one's value across any
 * synchronization. Today the call takes every token, and the load stays.
 */
public class FinalAcrossLock {

    static class Point {
        final int x;

        Point(int x) {
            this.x = x;
        }
    }

    static final Object LOCK = new Object();
    static int calls;

    // Recursive, so that Graal can't inline it before the analysis.
    static void logged(int n) {
        if (n > 0) {
            logged(n - 1);
        } else {
            synchronized (LOCK) {
                calls++;
            }
        }
    }

    static int demo(Point point, int n) {
        int first = point.x;
        logged(n);
        return first + point.x;
    }

    static int sink;

    public static void main(String[] args) {
        sink = demo(new Point(args.length + 2), args.length);
    }
}
