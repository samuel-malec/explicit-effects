package conversion;

/**
 * A load and a store of a static field: no object, so nothing to check. The
 * field's token goes in, through the load and the store, and out: each memory
 * operation takes one version of the token and gives the next.
 */
public class StaticFieldUpdate {

    static int total;

    static void demo(int amount) {
        total = total + amount;
    }

    public static void main(String[] args) {
        demo(args.length + 1);
    }
}
