package concurrency;

/**
 * An object stored into an array another thread can reach.
 */
public class PublishedByArray {

    static class Item { int value; Object link; }

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
        TABLE[args.length] = item;
        use(item, args.length);
    }
}
