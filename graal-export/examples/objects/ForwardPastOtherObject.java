package objects;

/**
 * The store between goes to another object: main only ever passes two different
 * counters. 
*/
public class ForwardPastOtherObject {

    static class Counter { int value; }

    static int demo(Counter counter, Counter other) {
        counter.value = 1;
        other.value = 2;
        return counter.value;
    }

    static int sink;

    public static void main(String[] args) {
        sink = demo(new Counter(), new Counter());
    }
}
