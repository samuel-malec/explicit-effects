package concurrency;

/**
 * An object stored into a field of an object another thread can reach,
 * the item is reachable through the box.
 */
public class PublishedByField {

    static class Item { int value; Object link; }

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
