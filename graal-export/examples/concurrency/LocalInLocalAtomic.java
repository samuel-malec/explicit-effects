package concurrency;

import java.util.concurrent.atomic.AtomicReference;

/**
 * An object set into an atomic reference that no one shares stays this thread's, though
 * another atomic reference is shared.
 */
public class LocalInLocalAtomic {

    static class Item { int value; Object link; }

    static void use(Item item, int n) {
        if (n > 0) {
            use(item, n - 1);
        } else {
            item.value++;
        }
    }

    static final AtomicReference<String> SHARED = new AtomicReference<>();

    static int sink;

    public static void main(String[] args) {
        SHARED.set("shared");
        AtomicReference<Item> mine = new AtomicReference<>();
        Item item = new Item();
        mine.set(item);
        use(mine.get(), args.length);
    }
}
