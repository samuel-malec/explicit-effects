/**
 * Locks that only one thread ever takes: objects with synchronized methods, allocated and used by
 * one thread, and kept where Graal's own escape analysis can't see them go: in an array, a field
 * of another object, a call it doesn't inline. What the program prints doesn't depend on the locks.
 */
public class Locks {

    /** A counter with synchronized methods, as Vector and StringBuffer have. */
    static final class SyncCounter {
        private int count;

        synchronized void add(int n) {
            count += n;
        }

        synchronized int get() {
            return count;
        }
    }

    static final class Pair {
        SyncCounter first = new SyncCounter();
        SyncCounter second = new SyncCounter();
    }

    // Recursive, so that inlining can't remove the call: the counter has left the caller.
    static void bump(SyncCounter counter, int depth, int n) {
        if (depth > 0) {
            bump(counter, depth - 1, n);
        } else {
            counter.add(n);
        }
    }

    /** Counters in an array, each taken in a loop. */
    static int inArray(int rounds) {
        SyncCounter[] counters = new SyncCounter[4];
        for (int i = 0; i < counters.length; i++) {
            counters[i] = new SyncCounter();
        }
        for (int i = 0; i < rounds; i++) {
            counters[i & 3].add(i);
        }
        int sum = 0;
        for (SyncCounter counter : counters) {
            sum += counter.get();
        }
        return sum;
    }

    /** Counters in the fields of an object, taken through a call that isn't inlined. */
    static int inObject(int rounds) {
        Pair pair = new Pair();
        for (int i = 0; i < rounds; i++) {
            bump((i & 1) == 0 ? pair.first : pair.second, 1, i);
        }
        return pair.first.get() + pair.second.get();
    }

    /** A StringBuffer, whose methods are synchronized, built up and read in a loop. */
    static int inBuffer(int rounds) {
        StringBuffer buffer = new StringBuffer();
        int sum = 0;
        for (int i = 0; i < rounds; i++) {
            buffer.append(i & 7);
            if (buffer.length() > 64) {
                sum += buffer.charAt(0);
                buffer.setLength(0);
            }
        }
        return sum + buffer.length();
    }

    /** A Vector and a Hashtable, whose methods are synchronized, used and thrown away. */
    static int inCollections(int rounds) {
        java.util.Vector<Integer> vector = new java.util.Vector<>();
        java.util.Hashtable<Integer, Integer> table = new java.util.Hashtable<>();
        for (int i = 0; i < rounds; i++) {
            vector.add(i);
            table.put(i & 15, i);
            if (vector.size() > 32) {
                vector.clear();
            }
        }
        return vector.size() + table.size();
    }

    public static void main(String[] args) {
        int rounds = 100_000 + args.length;
        System.out.println("array " + inArray(rounds));
        System.out.println("object " + inObject(rounds));
        System.out.println("buffer " + inBuffer(rounds));
        System.out.println("collections " + inCollections(rounds));
    }
}
