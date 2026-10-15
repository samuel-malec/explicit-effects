package conversion;

/**
 * An exception handler. The call's exception edge leads to a block that starts with
 * ExceptionObject: in the token form the handler's λ takes the exception as its
 * first parameter, as a phi. The handler checks the exception's class first, and
 * throws on what it doesn't catch. Making the exception reaches a call the
 * standalone analysis can't resolve, so the method takes every token (see
 * limits.OpaqueCall).
 */
public class CatchException {

    // Recursive, so that Graal can't inline it before the analysis.
    static int check(int n) {
        if (n < 0) {
            throw new IllegalArgumentException();
        }
        return n == 0 ? 0 : check(n - 1) + 1;
    }

    static int demo(int n) {
        try {
            return check(n);
        } catch (IllegalArgumentException e) {
            return -1;
        }
    }

    static int sink;

    public static void main(String[] args) {
        sink = demo(args.length - 1);
    }
}
