package deadstores;

/**
 * The simplest dead store: overwritten right away, with nothing between. Compare
 * what the export still has with what the rules leave.
 */
public class Adjacent {

    static class Counter { int value; }

    static void demo(Counter counter) {
        counter.value = 1;
        counter.value = 2;
    }

    public static void main(String[] args) {
        demo(new Counter());
    }
}
