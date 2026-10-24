package concurrency;

import java.lang.invoke.MethodHandles;
import java.lang.invoke.VarHandle;

/**
 * Control: an object stored through a variable handle into a field of an object no one shares stays
 * this thread's, though another box is shared through the same handle.
 */
public class LocalInLocalVarHandle {

    static class Item { int value; Object link; }

    // Recursive, so that inlining can't bring it into main: it reads and writes the item's field.
    static void use(Item item, int n) {
        if (n > 0) {
            use(item, n - 1);
        } else {
            item.value++;
        }
    }

    static class Box { Object item; }

    static final VarHandle ITEM;

    static {
        try {
            ITEM = MethodHandles.lookup().findVarHandle(Box.class, "item", Object.class);
        } catch (ReflectiveOperationException e) {
            throw new ExceptionInInitializerError(e);
        }
    }

    static final Box SHARED = new Box();

    static int sink;

    public static void main(String[] args) {
        ITEM.set(SHARED, "shared");
        Box mine = new Box();
        Item item = new Item();
        ITEM.set(mine, item);
        use(item, args.length);
    }
}
