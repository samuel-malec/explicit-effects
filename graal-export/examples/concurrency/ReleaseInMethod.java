package concurrency;

/**
 * A release inside the method: writing the volatile flag. The translation makes
 * it a `release` of every token, which reads the memory and leaves it as it was,
 * so the load after it takes the 5. Graal keeps the load: its volatile store
 * kills all of memory.
 */
public class ReleaseInMethod {

    static class Counter { int value; }

    static volatile boolean ready;

    static int demo(Counter counter) {
        counter.value = 5;
        ready = true;
        return counter.value;
    }

    static int sink;

    public static void main(String[] args) {
        sink = demo(new Counter());
    }
}
