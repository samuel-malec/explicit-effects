package forwarding;

/**
 * A load forwards from a load too: the second read of counter.value, after a call
 * that doesn't write it, takes the value the first read gave.
 */
public class RepeatedLoad {

    static class Counter { int value; }
    static class Link { Link next; }

    // Recursive, so that Graal can't inline it before the analysis.
    static int length(Link link) {
        return link == null ? 0 : 1 + length(link.next);
    }

    static int demo(Counter counter, Link list) {
        int before = counter.value;
        int n = length(list);
        return before + counter.value + n;
    }

    static int sink;

    public static void main(String[] args) {
        sink = demo(new Counter(), new Link());
    }
}
