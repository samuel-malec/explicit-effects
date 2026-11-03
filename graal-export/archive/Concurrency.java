/**
 * Calls that synchronize, with real threads: what a kill set may let through them and what it must not.
 */
public class Concurrency {

    static class Counter { int value; }

    static class Tally {
        int count;

        // Recursive, so that inlining can't remove the call. It locks the tally.
        synchronized void add(int n) {
            if (n > 0) {
                add(n - 1);
            } else {
                count++;
            }
        }
    }

    static final Object LOCK = new Object();
    static Counter shared = new Counter();
    static int calls;
    static boolean ready;

    // Recursive too. It takes the lock every thread takes: an acquire and a release others see.
    static void touch(int n) {
        if (n > 0) {
            touch(n - 1);
        } else {
            synchronized (LOCK) {
                calls++;
            }
        }
    }

    // The lock is the tally's, and only this thread reaches the tally: taking it orders this
    // thread with no one, so the load may take the 5 although the counter is in a static field.
    static int forwardAcrossLocalLock(Tally tally, int n) {
        Counter counter = shared;
        counter.value = 5;
        tally.add(n);
        return counter.value;
    }

    // The same through the lock every thread takes: another thread may have written the value
    // by the time the lock is free, so the load must read memory.
    static int readAcrossSharedLock(int n) {
        Counter counter = shared;
        counter.value = 6;
        touch(n);
        return counter.value;
    }

    // The worker takes the lock after it writes `ready`, so the first call of `touch` to take the
    // lock after that must show it: the loop has to load `ready` again after every call. A kill set
    // that lets `touch` write nothing lets the load out of the loop, and the loop never ends.
    static int waitForWorker() {
        while (!ready) {
            touch(0);
        }
        return 42;
    }

    static void work() {
        synchronized (LOCK) {
            ready = true;
        }
    }

    public static void main(String[] args) throws InterruptedException {
        int n = args.length;
        Tally tally = new Tally();
        int sum = forwardAcrossLocalLock(tally, n);
        sum += readAcrossSharedLock(n);
        Thread worker = new Thread(Concurrency::work);
        worker.start();
        sum += waitForWorker();
        worker.join();
        System.out.println("sum " + sum + " tally " + tally.count);
    }
}
