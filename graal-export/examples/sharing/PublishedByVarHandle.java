package sharing;

import java.lang.invoke.MethodHandles;
import java.lang.invoke.VarHandle;

/**
 * An object stored through a variable handle into a field of an object other threads reach: the
 * handle's store is the accessor every handle of the kind shares, and the analysis models it by
 * nothing, or by that one body. The arguments of the call say what it stores where.
 */
public class PublishedByVarHandle {

    static class Item { int value; Object link; }

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

    static final Box BOX = new Box();

    static int sink;

    public static void main(String[] args) {
        Item item = new Item();
        ITEM.set(BOX, item);
        use(item, args.length);
    }
}
