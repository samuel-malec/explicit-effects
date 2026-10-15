package conversion;

/**
 * The same load as NullCheck, through `this`, which is never null: no check, no
 * branch, one λ. Compare the two.
 */
public class ReceiverField {

    int value;

    int demo() {
        return value;
    }

    static int sink;

    public static void main(String[] args) {
        ReceiverField receiver = new ReceiverField();
        receiver.value = args.length;
        sink = receiver.demo();
    }
}
