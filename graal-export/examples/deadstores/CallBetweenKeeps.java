package deadstores;

/**
 * The call between the stores doesn't touch Counter.value, yet the first store
 * stays: the call may throw (any call may, StackOverflowError at least), and then
 * the method leaves with the 1 stored, which a handler up the stack may read. In
 * the token form the call's exception is a branch, which the rules make a guard
 * that `throws`: a guard every token passes, so h_value leaves the method there.
 */
public class CallBetweenKeeps {

    static class Counter { int value; }
    static class Link { Link next; }

    // Recursive, so that Graal can't inline it before the analysis.
    static int length(Link link) {
        return link == null ? 0 : 1 + length(link.next);
    }

    static int demo(Counter counter, Link list) {
        counter.value = 1;
        int n = length(list);
        counter.value = 2;
        return n;
    }

    static int sink;

    public static void main(String[] args) {
        sink = demo(new Counter(), new Link());
    }
}
