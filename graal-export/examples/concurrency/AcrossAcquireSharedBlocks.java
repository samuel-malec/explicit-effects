package concurrency;

/**
 * Control for AcrossAcquireLocal: the counter is in a static field, so another
 * thread may write its value and then set the flag. Once `poll` has read the
 * flag, this thread must see that write, so the load must read memory again.
 * Forwarding the 5 here is wrong under any partitioning.
 */
public class AcrossAcquireSharedBlocks {

    static class Counter { int value; }

    static volatile boolean ready;
    static Counter shared = new Counter();

    // Recursive, so that Graal can't inline it before the analysis.
    static boolean poll(int n) {
        return n > 0 ? poll(n - 1) : ready;
    }

    static int demo(int n) {
        Counter counter = shared;
        counter.value = 5;
        poll(n);
        return counter.value;
    }

    static int sink;

    public static void main(String[] args) {
        sink = demo(args.length);
    }
}
