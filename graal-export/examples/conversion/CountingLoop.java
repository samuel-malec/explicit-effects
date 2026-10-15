package conversion;

/**
 * A loop without memory. The loop header is a λ that the loop body jumps back to:
 * Graal's loop phis, i and sum, are its parameters, and each jump passes their next
 * values. Leaving the loop is the header's branch to the exit.
 */
public class CountingLoop {

    static int demo(int n) {
        int sum = 0;
        for (int i = 0; i < n; i++) {
            sum += i;
        }
        return sum;
    }

    static int sink;

    public static void main(String[] args) {
        sink = demo(args.length + 3);
    }
}
