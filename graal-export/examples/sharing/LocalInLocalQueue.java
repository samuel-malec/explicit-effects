package sharing;

import java.util.concurrent.ConcurrentLinkedQueue;

/**
 * An object queued in a queue no one shares stays this thread's, though another queue is shared.
 */
public class LocalInLocalQueue {

    static class Item { int value; Object link; }

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
