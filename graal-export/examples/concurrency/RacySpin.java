package concurrency;

/**
 * A loop that waits for a plain field to change. Nothing synchronizes, so if
 * another thread set the field, the program would have a data race, and the
 * Java memory model promises such a program almost nothing. Reading the field
 * once, before the loop, is then allowed, and the loop spins forever if it read
 * 0. This is not a control: the rules may hoist the load. We make no claims
 * about racy programs. Here no other thread exists, and `main` sets the field
 * first, so the loop ends at once.
 */
public class RacySpin {

    static class Counter { int value; }

    static void demo(Counter counter) {
        while (counter.value == 0) {
        }
    }

    public static void main(String[] args) {
        Counter counter = new Counter();
        counter.value = args.length + 1;
        demo(counter);
    }
}
