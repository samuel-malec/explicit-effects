package concurrency;

/**
 * An object another thread can reach through a static field
 */
public class PublishedByStatic {

    static class Item { int value; Object link; }

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
