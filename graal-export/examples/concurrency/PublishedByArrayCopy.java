package concurrency;

/**
 * An object in an array only this thread reaches, copied into one other threads reach: the
 * copy is not a store of the object, but it puts the object where they can read it.
 */
public class PublishedByArrayCopy {

    static class Item { int value; Object link; }

    // Recursive, so that inlining can't bring it into main: it reads and writes the item's field.
    static void use(Item item, int n) {
        if (n > 0) {
            use(item, n - 1);
        } else {
            item.value++;
        }
    }

    static final Item[] TABLE = new Item[4];

    static int sink;

    public static void main(String[] args) {
        Item item = new Item();
        Item[] mine = new Item[]{item};
        System.arraycopy(mine, 0, TABLE, args.length, 1);
        use(item, args.length);
    }
}
