package conversion;

/**
 * A call. `… run → k` names the callee as a closure, and `call k …` passes it the
 * arguments and the tokens its signature needs; it gives back the result, the
 * exception it threw (null when none), and the tokens. The caller then branches on
 * the exception. With --partition field the call takes only h_count, the field the
 * callee writes, not h_other, which only the caller writes.
 */
public class StaticCall {

    static int count;
    static int other;

    // Recursive, so that Graal can't inline it before the analysis.
    static void bump(int n) {
        if (n > 0) {
            count++;
            bump(n - 1);
        }
    }

    static void demo(int n) {
        other = n;
        bump(n);
    }

    public static void main(String[] args) {
        demo(args.length + 2);
    }
}
