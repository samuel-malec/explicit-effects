package conversion;

/**
 * A call to a method that touches no memory: with --partition field it takes no
 * token, so nothing orders it against the store after it. With one heap token it
 * takes the heap like every call.
 */
public class PureCall {

    static int total;

    // Recursive, so that Graal can't inline it before the analysis.
    static int fib(int n) {
        return n < 2 ? n : fib(n - 1) + fib(n - 2);
    }

    static void demo(int n) {
        total = fib(n);
    }

    public static void main(String[] args) {
        demo(args.length + 5);
    }
}
