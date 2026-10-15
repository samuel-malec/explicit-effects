package conversion;

/**
 * An allocation that escapes, by being returned. Escape analysis keeps the object
 * virtual until it escapes; there one CommitAllocation makes it with its fields'
 * first values, Java's zeros. The token form writes `new_k`, which takes the
 * rest-of-memory token, and an `init_k` for each field: no Java store, the object's
 * first values. Graal doesn't inline the constructor, which then runs as a call.
 */
public class NewObject {

    static class Point {
        int x;
        int y;

        Point(int x, int y) {
            this.x = x;
            this.y = y;
        }
    }

    static Point demo(int x, int y) {
        return new Point(x, y);
    }

    static Point sink;

    public static void main(String[] args) {
        sink = demo(args.length, 2);
    }
}
