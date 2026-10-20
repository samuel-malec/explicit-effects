package forwarding;

/**
 * The load is in one arm of a branch, its value stored above the branch.
 * We could pass the value down the branch and forward the load.
 */
public class IntoBranchArm {

    static class Counter { int value; }
    static class Link { Link next; }

    // Recursive, so that Graal can't inline it before the analysis.
    static int length(Link link) {
        return link == null ? 0 : 1 + length(link.next);
    }

    static int demo(Counter counter, Link list, boolean flag) {
        counter.value = 1;
        int n = length(list);
        if (flag) {
            n += counter.value;
        }
        return n;
    }

    static int sink;

    public static void main(String[] args) {
        sink = demo(new Counter(), new Link(), args.length > 0);
    }
}
