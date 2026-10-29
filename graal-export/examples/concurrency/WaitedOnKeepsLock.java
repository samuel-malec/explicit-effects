package concurrency;

/**
 * A lock on an object no other thread can reach, which the thread waits on: `wait` needs the monitor
 * held and throws without it, so the lock stays although nothing else could take it.
 */
public class WaitedOnKeepsLock {

    static class Gate {
        int opened;
    }

    static int pass(Gate gate, int n) throws InterruptedException {
        if (n > 0) {
            return pass(gate, n - 1);
        }
        synchronized (gate) {
            gate.wait(1);
            gate.opened++;
            return gate.opened;
        }
    }

    static int sink;

    public static void main(String[] args) throws InterruptedException {
        sink = pass(new Gate(), args.length);
    }
}
