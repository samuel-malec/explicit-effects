package forwarding;

/**
 * The load after the call reads the 5 stored before it, although `sum` reads
 * Counter.value, it doesn't modify it.
 */
public class AcrossReadingCall {

    static class Counter {
        int value;
        Counter next;
    }

    static int sum(Counter counter) {
        return counter == null ? 0 : counter.value + sum(counter.next);
    }

    static int demo(Counter counter) {
        counter.value = 5;
        int total = sum(counter);
        return counter.value + total;
    }

    static int sink;

    public static void main(String[] args) {
        sink = demo(new Counter());
    }
}
