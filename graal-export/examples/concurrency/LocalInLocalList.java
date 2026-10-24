package concurrency;

import java.util.ArrayList;

/**
 * Control: an object added to a list no one shares stays this thread's, though another list is shared.
 * The analysis that tells objects apart by type alone can't see it: every Object[] is one object,
 * and the shared list's array is one.
 */
public class LocalInLocalList {

    static class Item { int value; Object link; }

    // Recursive, so that inlining can't bring it into main: it reads and writes the item's field.
    static void use(Item item, int n) {
        if (n > 0) {
            use(item, n - 1);
        } else {
            item.value++;
        }
    }

    static final ArrayList<String> SHARED = new ArrayList<>();

    static int sink;

    public static void main(String[] args) {
        SHARED.add("shared");
        ArrayList<Item> mine = new ArrayList<>();
        Item item = new Item();
        mine.add(item);
        use(mine.get(0), args.length);
    }
}
