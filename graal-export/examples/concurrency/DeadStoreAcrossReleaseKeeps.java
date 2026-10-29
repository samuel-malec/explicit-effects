package concurrency;

/**
 * A store, a release, and a store that overwrites the first. Without
 * the release the first store would be dead, as in deadstores.Adjacent. But the
 * counter is in a static field, and another thread that reads the flag as true
 * must then see the 1, so the release reads Counter.value, and the first store
 * must stay. (With a counter only this thread reaches, it could go.)
 */
public class DeadStoreAcrossReleaseKeeps {

    static class Counter { int value; }

    static volatile boolean ready;
    static Counter shared = new Counter();

    static void demo() {
        Counter counter = shared;
        counter.value = 1;
        ready = true;
        counter.value = 2;
    }

    public static void main(String[] args) {
        demo();
    }
}
