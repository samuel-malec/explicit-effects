package conversion;

/**
 * A value that depends on the branch taken: Graal's ValuePhi at the merge becomes a
 * parameter of the merge's λ, and each arm passes its own value for it.
 */
public class ValueMerge {

    static int demo(int a, int b, boolean first) {
        return first ? a : b;
    }

    static int sink;

    public static void main(String[] args) {
        sink = demo(args.length, 7, args.length > 1);
    }
}
