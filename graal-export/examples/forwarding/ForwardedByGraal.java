package forwarding;

/**
 * Nothing for the rules to do: with nothing between the store and the load, Graal
 * forwards the 5 itself before the analysis, so the export has no load left.
 */
public class ForwardedByGraal {

    static class Counter { int value; }

    static int demo(Counter counter) {
        counter.value = 5;
        return counter.value;
    }

    static int sink;

    public static void main(String[] args) {
        sink = demo(new Counter());
    }
}
