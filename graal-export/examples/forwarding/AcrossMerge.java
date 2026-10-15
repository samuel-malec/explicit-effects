package forwarding;

/**
 * Both arms store, and the load after the merge reads whichever value its arm
 * stored: the rules split the merge, so that each arm jumps to a copy of it, up to
 * the load, that takes the arm's value as a parameter, as a phi.
 */
public class AcrossMerge {

    static class Counter { int value; }
    static class Link { Link next; }

    // Recursive, so that Graal can't inline it before the analysis.
    static int length(Link link) {
        return link == null ? 0 : 1 + length(link.next);
    }

    static int demo(Counter counter, Link list, boolean flag) {
        int n = 0;
        if (flag) {
            counter.value = 1;
            n = length(list);
        } else {
            counter.value = 2;
        }
        return counter.value + n;
    }

    static int sink;

    public static void main(String[] args) {
        sink = demo(new Counter(), new Link(), args.length > 0);
    }
}
