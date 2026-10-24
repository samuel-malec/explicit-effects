/**
 * Locks that only one thread ever takes, one lock class for each place the locked object is kept, so
 * that what thread escape finds for one place doesn't depend on another: in the fields of an object, in
 * an array, in a list, in a local the compiler can't see through. What the program prints doesn't depend
 * on the locks.
 */
public class LockShapes {

    /** A counter with synchronized methods, as Vector and StringBuffer have. */
    static final class FieldCounter {
        private int count;

        synchronized void add(int n) {
            count += n;
        }

        synchronized int get() {
            return count;
        }
    }

    static final class ArrayCounter {
        private int count;

        synchronized void add(int n) {
            count += n;
        }

        synchronized int get() {
            return count;
        }
    }

    static final class ListCounter {
        private int count;

        synchronized void add(int n) {
            count += n;
        }

        synchronized int get() {
            return count;
        }
    }

    static final class CallCounter {
        private int count;

        synchronized void add(int n) {
            count += n;
        }

        synchronized int get() {
            return count;
        }
    }

    static final class Pair {
        FieldCounter first = new FieldCounter();
        FieldCounter second = new FieldCounter();
    }

    // Recursive, so that inlining can't remove the call: the counter has left the caller. One for each
    // kind of counter, so that the lock of one is taken only by the objects of one place.
    static void bump(CallCounter counter, int depth, int n) {
        if (depth > 0) {
            bump(counter, depth - 1, n);
        } else {
            counter.add(n);
        }
    }

    static void bump(FieldCounter counter, int depth, int n) {
        if (depth > 0) {
            bump(counter, depth - 1, n);
        } else {
            counter.add(n);
        }
    }

    static void bump(ArrayCounter counter, int depth, int n) {
        if (depth > 0) {
            bump(counter, depth - 1, n);
        } else {
            counter.add(n);
        }
    }

    static void bump(ListCounter counter, int depth, int n) {
        if (depth > 0) {
            bump(counter, depth - 1, n);
        } else {
            counter.add(n);
        }
    }

    /** Counters in the fields of an object. */
    static int inFields(int rounds) {
        Pair pair = new Pair();
        for (int i = 0; i < rounds; i++) {
            bump((i & 1) == 0 ? pair.first : pair.second, 1, i);
        }
        return pair.first.get() + pair.second.get();
    }

    /** Counters in an array. */
    static int inArray(int rounds) {
        ArrayCounter[] counters = new ArrayCounter[4];
        for (int i = 0; i < counters.length; i++) {
            counters[i] = new ArrayCounter();
        }
        for (int i = 0; i < rounds; i++) {
            bump(counters[i & 3], 1, i);
        }
        int sum = 0;
        for (ArrayCounter counter : counters) {
            sum += counter.get();
        }
        return sum;
    }

    /** Counters in a list. */
    static int inList(int rounds) {
        java.util.ArrayList<ListCounter> counters = new java.util.ArrayList<>();
        for (int i = 0; i < 4; i++) {
            counters.add(new ListCounter());
        }
        for (int i = 0; i < rounds; i++) {
            bump(counters.get(i & 3), 1, i);
        }
        int sum = 0;
        for (ListCounter counter : counters) {
            sum += counter.get();
        }
        return sum;
    }

    /** A counter taken through a call that isn't inlined. */
    static int throughCalls(int rounds) {
        CallCounter counter = new CallCounter();
        for (int i = 0; i < rounds; i++) {
            bump(counter, 1, i);
        }
        return counter.get();
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

    public static void main(String[] args) {
        int rounds = 100_000 + args.length;
        System.out.println("fields " + inFields(rounds));
        System.out.println("array " + inArray(rounds));
        System.out.println("list " + inList(rounds));
        System.out.println("calls " + throughCalls(rounds));
        System.out.println("buffer " + inBuffer(rounds));
    }
}
