public class DeadStore {

    static class Counter { int value; int other; }
    static class Logger { int count; }

    static void deadStoreOtherField(Counter counter) {
        counter.value = 1; // dead store
        counter.other = 7;
        counter.value = 2;
    }

    public static void main(String[] args) {
        Counter counter = new Counter();
        deadStoreOtherField(counter);
        System.out.println(counter.value);
    }
}
