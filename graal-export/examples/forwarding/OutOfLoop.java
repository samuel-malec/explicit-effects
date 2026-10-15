package forwarding;

/**
 * Nothing in the loop writes Counter.value, but no store before the loop gives its
 * value: the rules peel the first iteration, whose load reads it, and the loop
 * takes that value, so the loop itself has no load left. A load can't simply move
 * above the loop: the loop may not run at all.
 */
public class OutOfLoop {

    static class Counter { int value; }
    static class Link { Link next; }

    // Recursive, so that Graal can't inline it before the analysis.
    static int length(Link link) {
        return link == null ? 0 : 1 + length(link.next);
    }

    static int demo(Counter counter, Link list, int times) {
        int sum = 0;
        for (int i = 0; i < times; i++) {
            sum += counter.value + length(list);
        }
        return sum;
    }

    static int sink;

    public static void main(String[] args) {
        // Not a constant, so that Graal can't unroll the loop.
        sink = demo(new Counter(), new Link(), args.length + 3);
    }
}
