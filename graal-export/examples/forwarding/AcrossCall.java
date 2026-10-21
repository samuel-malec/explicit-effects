package forwarding;

/**
 * The load after the call reads the 5 stored before it: `length` only reads
 * Link.next, therefore we don't have to load for the second time.
 */
public class AcrossCall {

    static class Counter { int value; }
    static class Link { Link next; }

    static int length(Link link) {
        return link == null ? 0 : 1 + length(link.next);
    }

    static int demo(Counter counter, Link list) {
        counter.value = 5;
        int n = length(list);
        return counter.value + n;
    }

    static int sink;

    public static void main(String[] args) {
        sink = demo(new Counter(), new Link());
    }
}
