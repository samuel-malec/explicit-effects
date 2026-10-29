package concurrency;

/**
 * An object stored into a box that no one shares stays this thread's.
 */
public class LocalInLocalObject {

    static class Item { int value; Object link; }

    static void use(Item item, int n) {
        if (n > 0) {
            use(item, n - 1);
        } else {
            item.value++;
        }
    }

    static class Box { Item item; }

    static int sink;

    public static void main(String[] args) {
        Box box = new Box();
        box.item = new Item();
        use(box.item, args.length);
    }
}
