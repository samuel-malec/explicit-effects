package deadstores;

/**
 * A store to another field comes between the two stores to counter.value. With a
 * token per field it takes h_other, not h_value, so the first store's token goes
 * straight to the overwrite, and the store is dead. With one heap token the store
 * between takes the heap, and the rule never looks past a memory operation.
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
