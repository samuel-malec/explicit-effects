package concurrency;

/**
 * The counter is handed to another thread, which writes its value.
 * `start` is a release and `join` an acquire, so after `join` this thread must
 * see the 7 the other thread stored. The load must read memory again, under
 * any partitioning, and a thread-escape analysis must count the counter as
 * shared.
 */
public class HandedToThreadBlocks {

    static class Counter { int value; }

    static final class Bump implements Runnable {
        private final Counter target;

        Bump(Counter target) {
            this.target = target;
        }

        public void run() {
            target.value = 7;
        }
    }

    static int demo(Counter counter) throws InterruptedException {
        counter.value = 5;
        Thread thread = new Thread(new Bump(counter));
        thread.start();
        thread.join();
        return counter.value;
    }

    static int sink;

    public static void main(String[] args) throws InterruptedException {
        sink = demo(new Counter());
    }
}
