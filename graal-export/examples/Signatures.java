/**
 * One method per signature rule: each stores to counter.value, makes a call,
 * and loads it again, so the tokens the call takes show what its signature
 * says it may touch.
 */
public class Signatures {

    static class Counter {
        int value;
    }

    static class Logger {
        int count;
    }

    static class Box {
        int v;

        synchronized void add(int n) {
            v += n;
        }
    }

    static class Flag {
        volatile int raised;
    }

    static final class Item {
        final int id;

        Item(int id) {
            this.id = id;
        }
    }

    interface Sink {
        void take(int n);
    }

    // Never instantiated: no call through Sink has a target.
    static final class Drain implements Sink {
        public void take(int n) {
        }
    }

    static void log(Logger logger) {
        logger.count++;
    }

    static void fill(int[] a) {
        a[0] = 1;
    }

    static void raise(Flag f) {
        f.raised = 1;
    }

    static native int fromOutside();

    static Box make() {
        return new Box();
    }

    static Item item(int id) {
        return new Item(id);
    }

    // Another field: the call takes Logger.count only.
    static int acrossField(Counter c, Logger logger) {
        c.value = 1;
        log(logger);
        return c.value;
    }

    // An array: the call takes int[] only.
    static int acrossArray(Counter c, int[] a) {
        c.value = 1;
        fill(a);
        return c.value;
    }

    // A monitor in the callee: it touches everything.
    static int acrossMonitor(Counter c, Box b) {
        c.value = 1;
        b.add(2);
        return c.value;
    }

    // A volatile store in the callee: it touches everything.
    static int acrossVolatile(Counter c, Flag f) {
        c.value = 1;
        raise(f);
        return c.value;
    }

    // A native callee has no facts: it touches everything.
    static int acrossNative(Counter c) {
        c.value = 1;
        int n = fromOutside();
        return c.value + n;
    }

    // No target: the analysis can't resolve the call, so it touches everything.
    static int acrossUnresolved(Counter c, Sink s) {
        c.value = 1;
        s.take(2);
        return c.value;
    }

    // An allocation touches the rest of memory, and Box's constructor nothing.
    static int acrossAllocation(Counter c) {
        c.value = 1;
        make();
        return c.value;
    }

    // A final field: the constructor returns the object, so its barrier needs
    // no token. The call takes Item.id, and the rest of memory to allocate.
    static int acrossFinalField(Counter c) {
        c.value = 1;
        item(2);
        return c.value;
    }

    public static void main(String[] args) {
        int n = args.length;
        Counter c = new Counter();
        int sum = acrossField(c, new Logger());
        sum += acrossArray(c, new int[n + 1]);
        sum += acrossMonitor(c, new Box());
        sum += acrossVolatile(c, new Flag());
        sum += acrossAllocation(c);
        sum += acrossFinalField(c);
        // Last, each on its own path: the analysis decides that neither returns.
        if (n > 7) {
            sum += acrossNative(c);
        } else {
            sum += acrossUnresolved(c, null);
        }
        System.out.println(sum);
    }
}
