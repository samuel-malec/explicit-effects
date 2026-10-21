package forwarding;

/**
 * Control for OutOfLoop: `countInto` writes Counter.value in every iteration, so
 * each load must read what the call left, and none leaves the loop.
 */
public class WritingCallInLoopBlocks {

    static class Counter { int value; }
    static class Link { Link next; }

    static void countInto(Counter counter, Link link) {
        if (link != null) {
            counter.value++;
            countInto(counter, link.next);
        }
    }

    static int demo(Counter counter, Link list, int times) {
        int sum = 0;
        for (int i = 0; i < times; i++) {
            countInto(counter, list);
            sum += counter.value;
        }
        return sum;
    }

    static int sink;

    public static void main(String[] args) {
        // Not a constant, so that Graal can't unroll the loop.
        sink = demo(new Counter(), new Link(), args.length + 3);
    }
}
