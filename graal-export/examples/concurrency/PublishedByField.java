package concurrency;

/**
 * An object stored into a field of one another thread can reach, which is in a static field:
 * the item is reached through the box.
 */
public class PublishedByField {

    static class Item { int value; Object link; }

    // Recursive, so that inlining can't bring it into main: it reads and writes the item's field.
    static void use(Item item, int n) {
        if (n > 0) {
            use(item, n - 1);
        } else {
            item.value++;
        }
    }

    static class Box { Item item; }

    static final Box BOX = new Box();

    static int sink;

    public static void main(String[] args) {
        Item item = new Item();
        BOX.item = item;
        use(item, args.length);
    }
}
