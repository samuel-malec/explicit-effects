package forwarding;

/**
 * The load is in one arm of a branch, its value stored above the branch: the rules
 * pass the value down the branch as a new parameter of both arms, and the load in
 * the arm takes it.
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
