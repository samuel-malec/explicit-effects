package concurrency;

import java.util.concurrent.ConcurrentLinkedQueue;

/**
 * An object handed to another thread through a queue: the queue's node holds it, and the node is
 * linked with compare-and-swap.
 */
public class PublishedByQueue {

    static class Item { int value; Object link; }

    // Recursive, so that inlining can't bring it into main: it reads and writes the item's field.
    static void use(Item item, int n) {
        if (n > 0) {
            use(item, n - 1);
        } else {
            item.value++;
        }
    }

    static final ConcurrentLinkedQueue<Item> QUEUE = new ConcurrentLinkedQueue<>();

    static int sink;

    public static void main(String[] args) {
        Item item = new Item();
        QUEUE.offer(item);
        use(item, args.length);
    }
}
