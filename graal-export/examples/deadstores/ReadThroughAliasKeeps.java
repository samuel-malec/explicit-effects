package deadstores;

/**
 * Between the stores a load goes through another reference, which may point to the
 * same object, and then reads the 1: the store stays. Reading alias.other first checks
 * alias for null before the stores, so nothing between them can throw, and only
 * the load keeps the store.
 */
public class ReadThroughAliasKeeps {

    static class Counter {
        int value;
        int other;
    }

    static int demo(Counter counter, Counter alias) {
        int seen = alias.other;
        counter.value = 1;
        seen += alias.value;
        counter.value = 2;
        return seen;
    }

    static int sink;

    public static void main(String[] args) {
        Counter counter = new Counter();
        sink = demo(counter, new Counter()) + demo(counter, counter);
    }
}
