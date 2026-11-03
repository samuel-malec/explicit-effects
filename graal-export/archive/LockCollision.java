/**
 * Two locks in one method that the facts label alike. {@code Shared.bump} is synchronized on an object
 * every thread reaches, and calls {@code Private.get}, a tiny synchronized method that Native Image may
 * inline before its analysis, on an object the call makes and no one else reaches. Both monitors are at
 * bytecode index 0 of their own frame, so a label made of the innermost index alone is the same for both.
 * Four threads add to {@code Shared.count} through the shared lock: the total is right only if that lock
 * is taken, and it is the lock a wrong judgement from the private one would remove.
 *
 * In the build of 24 Oct Native Image does not inline {@code Private.get} before its analysis (the facts list
 * it as a call of {@code Shared.bump}), so the two labels do not collide here and the program is a round trip
 * of a shared and a private lock in one method. The label collisions that do occur (267 in AWFY, 1,508 in
 * javac) are of other sites, which I did not classify; see F63.
 */
public class LockCollision {

    static final class Private {
        int value = 1;

        synchronized int get() {
            return value;
        }
    }

    static final class Shared {
        int count;

        synchronized int bump() {
            count++;
            Private local = new Private();
            return local.get();
        }

        synchronized int total() {
            return count;
        }
    }

    static final Shared SHARED = new Shared();
    static final int ROUNDS = 200_000;

    // Recursive, so that inlining can't remove the call: the counter has left the caller.
    static void bump(Shared shared, int depth) {
        if (depth > 0) {
            bump(shared, depth - 1);
        } else {
            shared.bump();
        }
    }

    static void work() {
        for (int i = 0; i < ROUNDS; i++) {
            bump(SHARED, 1);
        }
    }

    public static void main(String[] args) throws InterruptedException {
        Thread[] threads = new Thread[4];
        for (int i = 0; i < threads.length; i++) {
            threads[i] = new Thread(LockCollision::work);
            threads[i].start();
        }
        for (Thread thread : threads) {
            thread.join();
        }
        System.out.println("total " + SHARED.total());
    }
}
