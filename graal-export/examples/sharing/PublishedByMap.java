package sharing;

import java.util.concurrent.ConcurrentHashMap;

/**
 * An object put into a concurrent map that other threads reach.
 */
public class PublishedByMap {

    static class Item { int value; Object link; }

    static void use(Item item, int n) {
        if (n > 0) {
            use(item, n - 1);
        } else {
            item.value++;
        }
    }

    static final ConcurrentHashMap<String, Item> MAP = new ConcurrentHashMap<>();

    static int sink;

    public static void main(String[] args) {
        Item item = new Item();
        MAP.put("item", item);
        use(item, args.length);
    }
}
