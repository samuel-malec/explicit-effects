package conversion;

/**
 * A method without memory: its λ only computes values. With one heap token
 * (--partition none) it still takes the heap and gives it back; with a token per
 * field (--partition field) its signature is empty, and it takes no token at all.
 */
public class PureArithmetic {

    static int demo(int a, int b) {
        return a * b + 1;
    }

    static int sink;

    public static void main(String[] args) {
        sink = demo(args.length, 7);
    }
}
