package deadstores;

/**
 * A store to another field comes between the two stores to counter.value.
 */
public class OtherFieldBetween {

    static class Counter { int value; int other; }

    static void demo(Counter counter) {
        counter.value = 1;
        counter.other = 7;
        counter.value = 2;
    }

    public static void main(String[] args) {
        demo(new Counter());
    }
}
