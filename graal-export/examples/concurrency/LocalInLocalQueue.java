package concurrency;

import java.util.concurrent.ConcurrentLinkedQueue;

/**
 * Control: an object queued in a queue no one shares stays this thread's, though another queue is shared.
 */
public class LocalInLocalQueue {

    static class Item { int value; Object link; }

    // Recursive, so that inlining can't bring it into main: it reads and writes the item's field.
    static void use(Item item, int n) {
        if (n > 0) {
            use(item, n - 1);
        } else {
            item.value++;
        }
    }

    static final ConcurrentLinkedQueue<String> SHARED = new ConcurrentLinkedQueue<>();

    static int sink;

    public static void main(String[] args) {
        SHARED.offer("shared");
        ConcurrentLinkedQueue<Item> mine = new ConcurrentLinkedQueue<>();
        Item item = new Item();
        mine.offer(item);
        use(mine.poll(), args.length);
    }
}
