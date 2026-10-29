package concurrency;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * An object a task captures, submitted to an executor: a worker thread runs the task.
 */
public class PublishedByExecutor {

    static class Item { int value; Object link; }

    static void use(Item item, int n) {
        if (n > 0) {
            use(item, n - 1);
        } else {
            item.value++;
        }
    }

    static int sink;

    public static void main(String[] args) {
        Item item = new Item();
        ExecutorService pool = Executors.newSingleThreadExecutor();
        pool.submit(() -> item.value++);
        pool.shutdown();
        use(item, args.length);
    }
}
