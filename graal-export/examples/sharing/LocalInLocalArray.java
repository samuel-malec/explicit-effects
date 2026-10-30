package sharing;

/**
 * An object stored into an array that no one shares stays this thread's, though
 * another array is shared.
 */
public class LocalInLocalArray {

    static class Item { int value; Object link; }

    static void use(Item item, int n) {
        if (n > 0) {
            use(item, n - 1);
        } else {
            item.value++;
        }
    }

    static final Object[] SHARED = new Object[4];

    static int sink;

    public static void main(String[] args) {
        SHARED[args.length] = "shared";
        Item[] mine = new Item[2];
        mine[0] = new Item();
        use(mine[0], args.length);
    }
}
