package concurrency;

/**
 * The counter is in a static field. Another thread
 * may take the same lock, write the value and leave the lock; once `logged`
 * has taken it, this thread must see that write. The load must read memory
 * again, under any partitioning.
 */
public class AcrossLockSharedBlocks {

    static class Counter { int value; }

    static final Object LOCK = new Object();
    static int calls;
    static Counter shared = new Counter();

    static void logged(int n) {
        if (n > 0) {
            logged(n - 1);
        } else {
            synchronized (LOCK) {
                calls++;
            }
        }
    }

    static int demo(int n) {
        Counter counter = shared;
        counter.value = 5;
        logged(n);
        return counter.value;
    }

    static int sink;

    public static void main(String[] args) {
        sink = demo(args.length);
    }
}
