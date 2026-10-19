package concurrency;

/**
 * Control for ReleaseInMethod: an acquire inside the method, reading the
 * volatile flag. The counter is in a static field, so another thread may write
 * its value and then set the flag; once this thread has read the flag, it must
 * see that write. The translation makes the read an `acquire` of every token,
 * after which memory may have changed, and the load stays.
 */
public class AcquireInMethodBlocks {

    static class Counter { int value; }

    static volatile boolean ready;
    static Counter shared = new Counter();

    static int demo() {
        Counter counter = shared;
        counter.value = 5;
        boolean seen = ready;
        return seen ? counter.value : 0;
    }

    static int sink;

    public static void main(String[] args) {
        sink = demo();
    }
}
