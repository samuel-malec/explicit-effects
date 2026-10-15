package objects;

/**
 * The store between goes to another object: main only ever passes two different
 * counters. With a token per field both stores take h_value, so the load can't take
 * the 1; with a token per field of each set of objects the analysis tells apart
 * (--partition object-field), the other counter's store takes another token, and
 * the load takes the 1.
 */
public class ForwardPastOtherObject {

    static class Counter { int value; }

    static int demo(Counter counter, Counter other) {
        counter.value = 1;
        other.value = 2;
        return counter.value;
    }

    static int sink;

    public static void main(String[] args) {
        sink = demo(new Counter(), new Counter());
    }
}
