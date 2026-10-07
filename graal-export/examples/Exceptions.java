public class Exceptions {

    static class Counter {
        int value;
    }

    // c may be null: the branch that throws NullPointerException is a trap.
    static int read(Counter c) {
        return c.value;
    }

    // The path that throws for large n is a trap too.
    static int checked(int n) {
        if (n > 100) {
            throw new IllegalArgumentException();
        }
        return n;
    }

    // Catches and recovers. Under traps no handler ever runs, so this is refused.
    static int recover(int n) {
        try {
            return checked(n);
        } catch (IllegalArgumentException e) {
            return -1;
        }
    }

    public static void main(String[] args) {
        Counter c = args.length > 5 ? null : new Counter();
        int n = args.length;
        System.out.println(read(c) + checked(n) + recover(n));
    }
}
