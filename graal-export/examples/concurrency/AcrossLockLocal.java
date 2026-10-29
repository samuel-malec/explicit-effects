package concurrency;

/**
 * A lock between a store and a load: `logged` enters and leaves a monitor on a
 * static object, so it is an acquire and then a release. The counter is
 * allocated in `main` and no other thread can reach it, so the load may take
 * the 5. 
 */
public class AcrossLockLocal {

    static class Counter { int value; }

    static final Object LOCK = new Object();
    static int calls;

    static void logged(int n) {
        if (n > 0) {
            logged(n - 1);
        } else {
            synchronized (LOCK) {
                calls++;
            }
        }
    }

    static int demo(Counter counter, int n) {
        counter.value = 5;
        logged(n);
        return counter.value;
    }

    static int sink;

    public static void main(String[] args) {
        sink = demo(new Counter(), args.length);
    }
}
