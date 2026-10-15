package forwarding;

/**
 * The load after the call reads the 5 stored before it: `length` only reads
 * Link.next, so with a token per field the call doesn't take h_value, the load's
 * token comes straight from the store, and the load takes the 5. With one heap
 * token the call takes the heap, and the load stays. Graal keeps it either way:
 * its call kills all of memory.
 */
public class AcrossCall {

    static class Counter { int value; }
    static class Link { Link next; }

    // Recursive, so that Graal can't inline it before the analysis.
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
