package conversion;

/**
 * Throwing. The method makes the exception, an allocation and a constructor call,
 * and Graal's Unwind gives it to the caller: the token form sets `exc`, gives back
 * every token, and no result (`bot`). Making the exception reaches a call the
 * standalone analysis can't resolve, so the method takes every token (see
 * limits.OpaqueCall).
 */
public class ThrowException {

    static int demo(int n) {
        if (n < 0) {
            throw new IllegalStateException();
        }
        return n;
    }

    static int sink;

    public static void main(String[] args) {
        sink = demo(args.length);
    }
}
