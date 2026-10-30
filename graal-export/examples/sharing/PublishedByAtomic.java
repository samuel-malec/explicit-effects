package sharing;

import java.util.concurrent.atomic.AtomicReference;

/**
 * An object set into an atomic reference that other threads reach
 */
public class PublishedByAtomic {

    static class Item { int value; Object link; }

    static void use(Item item, int n) {
        if (n > 0) {
            use(item, n - 1);
        } else {
            item.value++;
        }
    }

    static final AtomicReference<Item> REFERENCE = new AtomicReference<>();

    static int sink;

    public static void main(String[] args) {
        Item item = new Item();
        REFERENCE.set(item);
        use(item, args.length);
    }
}
