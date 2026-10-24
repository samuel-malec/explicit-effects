/**
 * Locks that must stay, next to locks that can go, with real threads. Four threads add to one counter
 * through its synchronized method: the total is right only if the lock is taken. Each thread also adds
 * to a counter of its own, made in the thread and kept in the field of an object the thread makes, with
 * its own synchronized method: no other thread reaches it, and its lock can go.
 *
 * The control: claim the shared counter's lock is thread-local (LIE_LOCKS='LocksShared$SharedCounter.add(I)V'
 * to graal-native/run.sh, mode locks); four threads then lose updates, and the total is wrong.
 */
public class LocksShared {

    static final class SharedCounter {
        private int count;

        synchronized void add(int n) {
            count += n;
        }

        synchronized int get() {
            return count;
        }
    }

    static final class PrivateCounter {
        private int count;

        synchronized void add(int n) {
            count += n;
        }

        synchronized int get() {
            return count;
        }
    }

    static final class Holder {
        PrivateCounter counter = new PrivateCounter();
    }

    static final SharedCounter SHARED = new SharedCounter();
    static final int ROUNDS = 200_000;

    // Recursive, so that inlining can't remove the calls: the counters have left the caller.
    static void bump(SharedCounter counter, int depth, int n) {
        if (depth > 0) {
            bump(counter, depth - 1, n);
        } else {
            counter.add(n);
        }
    }

    static void bump(PrivateCounter counter, int depth, int n) {
        if (depth > 0) {
            bump(counter, depth - 1, n);
        } else {
            counter.add(n);
        }
    }

    static final int[] PRIVATE_SUMS = new int[4];

    static void work(int index) {
        Holder holder = new Holder();
        for (int i = 0; i < ROUNDS; i++) {
            bump(SHARED, 1, 1);
            bump(holder.counter, 1, i & 3);
        }
        PRIVATE_SUMS[index] = holder.counter.get();
    }

    public static void main(String[] args) throws InterruptedException {
        Thread[] threads = new Thread[4];
        for (int i = 0; i < threads.length; i++) {
            int index = i;
            threads[i] = new Thread(() -> work(index));
            threads[i].start();
        }
        for (Thread thread : threads) {
            thread.join();
        }
        int privateSum = 0;
        for (int sum : PRIVATE_SUMS) {
            privateSum += sum;
        }
        System.out.println("shared " + SHARED.get() + " private " + privateSum);
    }
}
