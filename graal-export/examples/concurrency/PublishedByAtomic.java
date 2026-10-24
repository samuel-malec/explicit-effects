package concurrency;

import java.util.concurrent.atomic.AtomicReference;

/**
 * An object set into an atomic reference that other threads reach: the store is a compare-and-swap
 * or a variable handle's, which the analysis models by nothing, or by the code of the one
 * accessor every atomic uses.
 */
public class PublishedByAtomic {

    static class Item { int value; Object link; }

    // Recursive, so that inlining can't bring it into main: it reads and writes the item's field.
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
