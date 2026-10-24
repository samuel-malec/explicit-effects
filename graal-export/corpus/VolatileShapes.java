/**
 * Volatile fields of objects only one thread reaches, one class for each place the object is kept, as
 * LockShapes has for locks: a volatile write costs a fence, and a field only one thread reaches
 * orders this thread with no other.
 */
public class VolatileShapes {

    static final class FieldTicker {
        volatile int ticks;

        void tick(int n) {
            ticks = ticks + n;
        }
    }

    static final class ArrayTicker {
        volatile int ticks;

        void tick(int n) {
            ticks = ticks + n;
        }
    }

    static final class Pair {
        FieldTicker first = new FieldTicker();
        FieldTicker second = new FieldTicker();
    }

    // Recursive, so that inlining can't remove the call: the object has left the caller.
    static void bump(FieldTicker ticker, int depth, int n) {
        if (depth > 0) {
            bump(ticker, depth - 1, n);
        } else {
            ticker.tick(n);
        }
    }

    static void bump(ArrayTicker ticker, int depth, int n) {
        if (depth > 0) {
            bump(ticker, depth - 1, n);
        } else {
            ticker.tick(n);
        }
    }

    /** Tickers in the fields of an object. */
    static int inFields(int rounds) {
        Pair pair = new Pair();
        for (int i = 0; i < rounds; i++) {
            bump((i & 1) == 0 ? pair.first : pair.second, 1, i);
        }
        return pair.first.ticks + pair.second.ticks;
    }

    /** Tickers in an array. */
    static int inArray(int rounds) {
        ArrayTicker[] tickers = new ArrayTicker[4];
        for (int i = 0; i < tickers.length; i++) {
            tickers[i] = new ArrayTicker();
        }
        for (int i = 0; i < rounds; i++) {
            bump(tickers[i & 3], 1, i);
        }
        int sum = 0;
        for (ArrayTicker ticker : tickers) {
            sum += ticker.ticks;
        }
        return sum;
    }

    public static void main(String[] args) {
        int rounds = 100_000 + args.length;
        System.out.println("fields " + inFields(rounds));
        System.out.println("array " + inArray(rounds));
    }
}
