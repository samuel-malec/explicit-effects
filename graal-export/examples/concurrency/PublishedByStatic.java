package concurrency;

/**
 * An object another thread can reach through a static field: every thread reaches
 * the field, so it reaches the item.
 */
public class PublishedByStatic {

    static class Item { int value; Object link; }

    // Recursive, so that inlining can't bring it into main: it reads and writes the item's field.
    static void use(Item item, int n) {
        if (n > 0) {
            use(item, n - 1);
        } else {
            item.value++;
        }
    }

    static Item published;

    static int sink;

    public static void main(String[] args) {
        Item item = new Item();
        published = item;
        use(item, args.length);
    }
}
