package forwarding;

/**
 * Each iteration reads what the iteration before stored, the first one the 1
 * stored before the loop: the header's new parameter is a loop-carried phi, which
 * the entry passes the 1 for and the back edge the i the body stored.
 */
public class LoopCarried {

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
            counter.value = i;
        }
        return sum;
    }

    static int sink;

    public static void main(String[] args) {
        // Not a constant, so that Graal can't unroll the loop.
        sink = demo(new Counter(), new Link(), args.length + 3);
    }
}
