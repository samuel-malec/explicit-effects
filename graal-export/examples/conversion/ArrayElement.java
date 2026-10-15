package conversion;

/**
 * Array elements: `aget_int` and `aset_int` on the token of all int arrays, after
 * the checks Java makes, that the array isn't null and the index is in bounds. Each
 * failed check is a branch to a λ that throws.
 */
public class ArrayElement {

    static int demo(int[] values, int i) {
        values[i] = values[i] + 1;
        return values.length;
    }

    static int sink;

    public static void main(String[] args) {
        sink = demo(new int[4], args.length);
    }
}
