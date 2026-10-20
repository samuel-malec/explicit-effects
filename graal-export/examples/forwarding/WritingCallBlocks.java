package forwarding;

/**
 * Control for AcrossCall: `countInto` writes Counter.value,
 * and the load must read what the call left.
 */
public class WritingCallBlocks {

    static class Counter { int value; }
    static class Link { Link next; }

    // Recursive, so that Graal can't inline it before the analysis.
    static void countInto(Counter counter, Link link) {
        if (link != null) {
            counter.value++;
            countInto(counter, link.next);
        }
    }

    static int demo(Counter counter, Link list) {
        counter.value = 5;
        countInto(counter, list);
        return counter.value;
    }

    static int sink;

    public static void main(String[] args) {
        sink = demo(new Counter(), new Link());
    }
}
