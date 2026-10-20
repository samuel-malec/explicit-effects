package forwarding;

/**
 * The value stored before the loop lasts through it: nothing in the loop writes
 * Counter.value, and therefore the load is loop invariant. 
 */
public class IntoLoop {

    static class Counter { int value; }
    static class Link { Link next; }

    // Recursive, so that Graal can't inline it before the analysis.
    static int length(Link link) {
        return link == null ? 0 : 1 + length(link.next);
    }

    static int demo(Counter counter, Link list, int times) {
        counter.value = 1;
        int sum = 0;
        for (int i = 0; i < times; i++) {
            sum += length(list) + counter.value;
        }
        return sum;
    }

    static int sink;

    public static void main(String[] args) {
        // Not a constant, so that Graal can't unroll the loop.
        sink = demo(new Counter(), new Link(), args.length + 3);
    }
}
